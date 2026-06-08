/**
 * ReClip audio trim UI.
 *
 * Routes processing to the backend (native ffmpeg) when available — desktop or local server.
 * Falls back to ffmpeg.wasm in the browser when the backend trim endpoint is disabled,
 * which is the case on the public hosted instance.
 */
(function () {
  'use strict';

  // ---------------- State ----------------
  const state = {
    source: null,           // { kind: 'file' | 'job', file?: File, jobId?: string, name: string }
    duration: 0,
    backendAvailable: false,
    wavesurfer: null,
    regions: null,
    region: null,
    ffmpegWasm: null,       // lazy-loaded ffmpeg.wasm instance
  };

  // ---------------- DOM ----------------
  const $ = (id) => document.getElementById(id);
  const els = {
    dropzone: $('dropzone'),
    fileInput: $('file-input'),
    recentSelect: $('recent-select'),
    panel: $('trim-panel'),
    fileName: $('file-name'),
    fileDuration: $('file-duration'),
    waveform: $('waveform'),
    waveformOverlay: $('waveform-overlay'),
    waveformOverlayText: $('waveform-overlay-text'),
    playBtn: $('play-btn'),
    iconPlay: $('icon-play'),
    iconPause: $('icon-pause'),
    currentTime: $('current-time'),
    startTime: $('start-time'),
    endTime: $('end-time'),
    exportBtn: $('export-btn'),
    status: $('status'),
    modeLabels: document.querySelectorAll('[data-mode-label]'),
    modeHint: $('mode-hint'),
    engineBadge: $('engine-badge'),
  };

  // ---------------- Helpers ----------------
  function fmt(secs) {
    if (!isFinite(secs) || secs < 0) secs = 0;
    const m = Math.floor(secs / 60);
    const s = secs - m * 60;
    return `${m}:${s.toFixed(s < 10 ? 1 : 1).padStart(4, '0')}`;
  }

  function parseTime(value) {
    if (value == null) return 0;
    const s = String(value).trim();
    if (!s) return 0;
    if (s.includes(':')) {
      const parts = s.split(':').map(Number);
      let total = 0;
      for (const p of parts) total = total * 60 + (isNaN(p) ? 0 : p);
      return total;
    }
    const n = Number(s);
    return isNaN(n) ? 0 : n;
  }

  function setStatus(text, kind) {
    els.status.textContent = text;
    els.status.className = 'status ' + (kind || 'info');
    if (!text) els.status.classList.add('hidden');
  }
  function clearStatus() { setStatus('', null); els.status.classList.add('hidden'); }

  // Overlay over the waveform area (shows spinner + status while loading).
  function showOverlay(text) {
    if (text) els.waveformOverlayText.textContent = text;
    els.waveformOverlay.classList.remove('hidden');
  }
  function hideOverlay() {
    els.waveformOverlay.classList.add('hidden');
  }

  // Reliable duration detection via HTML5 <audio> element. For raw .aac files
  // that report Infinity initially, seek to the end to force the browser to
  // scan the stream and report the real duration. This is the standard trick.
  function detectDurationFromAudio(file) {
    return new Promise((resolve) => {
      const audio = new Audio();
      const url = URL.createObjectURL(file);
      audio.preload = 'metadata';
      audio.src = url;

      let resolved = false;
      const done = (d) => {
        if (resolved) return;
        resolved = true;
        try { audio.pause(); } catch (_) {}
        audio.removeAttribute('src');
        try { audio.load(); } catch (_) {}
        URL.revokeObjectURL(url);
        resolve(isFinite(d) && d > 0 ? d : 0);
      };
      const timeout = setTimeout(() => done(0), 15000);

      audio.addEventListener('loadedmetadata', () => {
        if (audio.duration === Infinity || isNaN(audio.duration)) {
          // Seek to a very large time to force the browser to scan the file.
          audio.currentTime = 1e100;
          audio.addEventListener('timeupdate', function once() {
            audio.removeEventListener('timeupdate', once);
            clearTimeout(timeout);
            done(audio.duration);
          });
        } else {
          clearTimeout(timeout);
          done(audio.duration);
        }
      });

      audio.addEventListener('error', () => {
        clearTimeout(timeout);
        done(0);
      });
    });
  }

  // ---------------- Capabilities ----------------
  async function detectCapabilities() {
    try {
      const r = await fetch('/api/capabilities');
      if (r.ok) {
        const data = await r.json();
        state.backendAvailable = !!data.trimBackend;
      }
    } catch (e) {
      state.backendAvailable = false;
    }
    els.engineBadge.textContent = state.backendAvailable
      ? 'Engine: native ffmpeg (local)'
      : 'Engine: ffmpeg.wasm (browser)';
  }

  // ---------------- Recent downloads ----------------
  async function loadRecentDownloads() {
    try {
      const r = await fetch('/api/recent-downloads');
      if (!r.ok) return;
      const items = await r.json();
      if (!items.length) return;
      els.recentSelect.disabled = false;
      els.recentSelect.innerHTML = '<option value="">— Select a recent download —</option>' +
        items.map(i => `<option value="${i.id}">${escapeHtml(i.filename || i.title || i.id)}</option>`).join('');
      els.recentSelect.addEventListener('change', onRecentSelect);
    } catch (e) {
      // No-op; recent downloads are optional.
    }
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    })[c]);
  }

  async function onRecentSelect() {
    const jobId = els.recentSelect.value;
    if (!jobId) return;
    setStatus('Loading…', 'info');
    try {
      const r = await fetch(`/api/file/${jobId}`);
      if (!r.ok) throw new Error('Could not load file from session');
      const blob = await r.blob();
      const name = (els.recentSelect.options[els.recentSelect.selectedIndex]?.text || 'audio.aac').trim();
      const file = new File([blob], name, { type: blob.type || 'audio/aac' });
      await loadSource({ kind: 'job', file, jobId, name });
      clearStatus();
    } catch (e) {
      setStatus(e.message || 'Failed to load', 'error');
    }
  }

  // ---------------- File picking ----------------
  els.dropzone.addEventListener('click', () => els.fileInput.click());
  els.fileInput.addEventListener('change', (e) => {
    const file = e.target.files && e.target.files[0];
    if (file) loadSource({ kind: 'file', file, name: file.name });
  });
  ['dragenter', 'dragover'].forEach(evt => {
    els.dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      els.dropzone.classList.add('drag-over');
    });
  });
  ['dragleave', 'drop'].forEach(evt => {
    els.dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      els.dropzone.classList.remove('drag-over');
    });
  });
  els.dropzone.addEventListener('drop', (e) => {
    const file = e.dataTransfer.files && e.dataTransfer.files[0];
    if (file) loadSource({ kind: 'file', file, name: file.name });
  });

  // ---------------- Load source into waveform ----------------
  async function loadSource(src) {
    state.source = src;
    state.duration = 0;
    els.fileName.textContent = src.name;
    els.fileDuration.textContent = '…';
    els.panel.classList.remove('hidden');
    clearStatus();
    showOverlay('Loading audio…');

    // Tear down any previous wavesurfer instance to avoid leaks.
    if (state.wavesurfer) {
      try { state.wavesurfer.destroy(); } catch (_) {}
      state.wavesurfer = null;
      state.region = null;
    }
    els.waveform.innerHTML = '';

    const ws = WaveSurfer.create({
      container: '#waveform',
      waveColor: getComputedStyle(document.documentElement).getPropertyValue('--muted').trim() || '#9c9889',
      progressColor: getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#e85d2a',
      height: 96,
      cursorColor: getComputedStyle(document.documentElement).getPropertyValue('--fg').trim() || '#3a3a38',
      cursorWidth: 1,
      barWidth: 2,
      barGap: 1,
      barRadius: 2,
    });
    state.wavesurfer = ws;
    const regionsPlugin = ws.registerPlugin(WaveSurfer.Regions.create());
    state.regions = regionsPlugin;

    ws.on('loading', (percent) => {
      if (percent < 100) {
        showOverlay(`Reading file… ${percent | 0}%`);
      } else {
        showOverlay('Decoding audio… (large files may take a moment)');
      }
    });

    const url = URL.createObjectURL(src.file);
    ws.load(url).catch((err) => {
      hideOverlay();
      setStatus(`Failed to load audio: ${err.message || err}`, 'error');
    });

    const applyDuration = () => {
      let d = ws.getDuration();
      if (!isFinite(d) || d <= 0) {
        try {
          const decoded = ws.getDecodedData();
          if (decoded && isFinite(decoded.duration) && decoded.duration > 0) {
            d = decoded.duration;
          }
        } catch (_) {}
      }
      // Latch: never overwrite a known-good duration with 0.
      if (d > 0 && d > state.duration) {
        state.duration = d;
        els.fileDuration.textContent = fmt(state.duration);
        els.endTime.value = fmt(state.duration);
        ensureRegion(0, state.duration);
        updateCurrentTime(ws.getCurrentTime() || 0);
      }
    };
    ws.on('ready', () => { applyDuration(); hideOverlay(); });
    ws.on('decode', () => { applyDuration(); showOverlay('Drawing waveform…'); });
    ws.on('audioprocess', (t) => updateCurrentTime(t));
    ws.on('seeking', (t) => updateCurrentTime(t));

    // Parallel: HTML5 audio element gives reliable duration even for raw AAC.
    detectDurationFromAudio(src.file).then(d => {
      if (d > 0 && d > state.duration) {
        state.duration = d;
        els.fileDuration.textContent = fmt(state.duration);
        els.endTime.value = fmt(state.duration);
        ensureRegion(0, state.duration);
        updateCurrentTime(ws.getCurrentTime() || 0);
      }
    }).catch(() => {});

    ws.on('finish', () => setPlayIcon(false));
    ws.on('play', () => setPlayIcon(true));
    ws.on('pause', () => setPlayIcon(false));

    // Safety: if 'ready' never fires (visual decode failed for an unusual file),
    // hide the overlay so the user can still trim using time inputs. 90s covers
    // very long files (hours-long AAC takes a while to decode).
    setTimeout(() => {
      if (!els.waveformOverlay.classList.contains('hidden')) {
        hideOverlay();
      }
    }, 90000);
  }

  function ensureRegion(start, end) {
    if (!state.regions) return;
    if (state.region) {
      state.region.remove();
      state.region = null;
    }
    state.region = state.regions.addRegion({
      start: Math.max(0, start),
      end: Math.min(state.duration, end),
      color: 'rgba(232, 93, 42, 0.18)',
      drag: true,
      resize: true,
    });
    state.region.on('update-end', () => {
      els.startTime.value = fmt(state.region.start);
      els.endTime.value = fmt(state.region.end);
    });
  }

  // ---------------- Time input sync ----------------
  function syncInputsToRegion() {
    if (!state.region) return;
    const start = Math.max(0, Math.min(parseTime(els.startTime.value), state.duration));
    let end = Math.max(0, Math.min(parseTime(els.endTime.value), state.duration));
    if (end <= start) end = Math.min(start + 0.5, state.duration);
    state.region.setOptions({ start, end });
  }
  els.startTime.addEventListener('change', syncInputsToRegion);
  els.endTime.addEventListener('change', syncInputsToRegion);

  // ---------------- Playback ----------------
  els.playBtn.addEventListener('click', () => {
    if (!state.wavesurfer) return;
    state.wavesurfer.playPause();
  });
  function setPlayIcon(playing) {
    els.iconPlay.style.display = playing ? 'none' : 'block';
    els.iconPause.style.display = playing ? 'block' : 'none';
  }
  function updateCurrentTime(t) {
    els.currentTime.textContent = `${fmt(t)} / ${fmt(state.duration)}`;
  }

  // ---------------- Mode toggle ----------------
  document.querySelectorAll('input[name="mode"]').forEach(input => {
    input.addEventListener('change', () => {
      els.modeLabels.forEach(lbl => {
        lbl.classList.toggle('selected', lbl.querySelector('input').checked);
      });
      const mode = document.querySelector('input[name="mode"]:checked').value;
      els.modeHint.textContent = mode === 'copy'
        ? 'Fast: instant, cuts snap to keyframes (~1s accuracy). Precise: exact cuts, takes a few seconds.'
        : 'Precise: exact cuts to the millisecond, re-encodes to AAC. Slightly slower, slightly larger file.';
    });
  });

  // ---------------- Export ----------------
  els.exportBtn.addEventListener('click', async () => {
    if (!state.source) {
      setStatus('Load an audio file first.', 'error');
      return;
    }
    const start = parseTime(els.startTime.value);
    const end = parseTime(els.endTime.value);
    if (end <= start) {
      setStatus('End time must be after start time.', 'error');
      return;
    }
    const mode = document.querySelector('input[name="mode"]:checked').value;

    els.exportBtn.disabled = true;
    setStatus('Trimming…', 'info');

    try {
      const blob = state.backendAvailable
        ? await trimViaBackend(state.source, start, end, mode)
        : await trimViaWasm(state.source.file, start, end, mode);

      const baseName = state.source.name.replace(/\.[^.]+$/, '') || 'audio';
      const ext = inferExt(state.source.name);
      const downloadName = `${baseName}_trimmed${ext}`;
      triggerDownload(blob, downloadName);
      setStatus('Done. Trimmed file downloaded.', 'success');
    } catch (e) {
      console.error(e);
      setStatus(e.message || 'Trim failed', 'error');
    } finally {
      els.exportBtn.disabled = false;
    }
  });

  function inferExt(name) {
    const m = /\.([a-z0-9]+)$/i.exec(name);
    return m ? '.' + m[1].toLowerCase() : '.aac';
  }

  function triggerDownload(blob, name) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  // ---------------- Backend path ----------------
  async function trimViaBackend(source, start, end, mode) {
    const fd = new FormData();
    fd.append('start', String(start));
    fd.append('end', String(end));
    fd.append('mode', mode);
    if (source.kind === 'job' && source.jobId) {
      fd.append('job_id', source.jobId);
    } else {
      fd.append('file', source.file);
    }
    const r = await fetch('/api/trim', { method: 'POST', body: fd });
    if (!r.ok) {
      let msg = 'Backend trim failed';
      try { msg = (await r.json()).error || msg; } catch (_) {}
      throw new Error(msg);
    }
    return await r.blob();
  }

  // ---------------- ffmpeg.wasm path (0.11.6 — simpler, more reliable than 0.12) ----------------
  async function ensureFfmpegWasm() {
    if (state.ffmpegWasm) return state.ffmpegWasm;
    if (!window.FFmpeg) {
      throw new Error('ffmpeg.wasm script failed to load. Check your network connection.');
    }
    setStatus('Loading ffmpeg.wasm (~25 MB, first time only)…', 'info');

    const { createFFmpeg, fetchFile } = window.FFmpeg;
    const ffmpeg = createFFmpeg({
      log: false,
      corePath: 'https://unpkg.com/@ffmpeg/core@0.11.0/dist/ffmpeg-core.js',
    });

    // Fail fast if load hangs (cross-origin worker stalls happen otherwise).
    const loadPromise = ffmpeg.load();
    const timeoutPromise = new Promise((_, reject) =>
      setTimeout(() => reject(new Error('ffmpeg.wasm load timed out after 90s. Try refreshing.')), 90000)
    );
    await Promise.race([loadPromise, timeoutPromise]);

    state.ffmpegWasm = { ffmpeg, fetchFile };
    return state.ffmpegWasm;
  }

  async function trimViaWasm(file, start, end, mode) {
    const { ffmpeg, fetchFile } = await ensureFfmpegWasm();
    const ext = inferExt(file.name).replace('.', '') || 'aac';
    const inName = `in.${ext}`;
    const outName = `out.${ext}`;
    ffmpeg.FS('writeFile', inName, await fetchFile(file));

    // Raw .aac streams have no timestamps, so `-c copy` with -ss/-to silently
    // produces a 0-byte file. Force re-encode for .aac regardless of mode.
    // M4A, MP3, WAV, OGG, FLAC have proper timestamps and copy works.
    const mustReencode = ext === 'aac';
    const useCopy = mode === 'copy' && !mustReencode;

    let args;
    if (useCopy) {
      args = ['-ss', String(start), '-to', String(end), '-i', inName, '-c', 'copy', outName];
    } else {
      const codec = (ext === 'aac' || ext === 'm4a') ? 'aac'
                  : ext === 'mp3' ? 'libmp3lame'
                  : ext === 'ogg' ? 'libvorbis'
                  : ext === 'wav' ? 'pcm_s16le'
                  : ext === 'flac' ? 'flac'
                  : 'aac';
      args = ['-i', inName, '-ss', String(start), '-to', String(end), '-c:a', codec];
      if (codec !== 'pcm_s16le' && codec !== 'flac') args.push('-b:a', '192k');
      args.push(outName);
    }

    setStatus(mustReencode && mode === 'copy'
      ? 'Trimming (raw AAC requires re-encode)…'
      : 'Trimming in your browser…', 'info');
    await ffmpeg.run(...args);
    const data = ffmpeg.FS('readFile', outName);

    if (!data || data.byteLength === 0) {
      try { ffmpeg.FS('unlink', inName); } catch (_) {}
      try { ffmpeg.FS('unlink', outName); } catch (_) {}
      throw new Error('ffmpeg produced an empty file. Try Precise (re-encode) mode.');
    }

    try { ffmpeg.FS('unlink', inName); } catch (_) {}
    try { ffmpeg.FS('unlink', outName); } catch (_) {}

    const mime = ext === 'aac' || ext === 'm4a' ? 'audio/aac'
               : ext === 'mp3' ? 'audio/mpeg'
               : ext === 'wav' ? 'audio/wav'
               : ext === 'ogg' ? 'audio/ogg'
               : 'application/octet-stream';
    return new Blob([data.buffer], { type: mime });
  }

  // ---------------- Boot ----------------
  detectCapabilities();
  loadRecentDownloads();
})();
