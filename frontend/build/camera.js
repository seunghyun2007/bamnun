/* Camera screen (docs/SPEC.md, section 13): the Signals panel, Retry, and
   full screen in landscape.

   Full screen moves the same <img> into an overlay, so there is still only one
   video stream. On the phone the Capacitor screen-orientation plugin turns
   the screen to landscape; in a browser the overlay is rotated 90 degrees with
   CSS instead. The close button sits in the same corner as the expand one. */
DYN.Camera = function (root) {
  const $ = (s) => root.querySelector(s);
  const box = $('#cmBox'), img = box.querySelector('[data-live="video"]');
  const list = $('#cmSignalList'), tog = $('#cmSignals');
  const CLOSE = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>';

  // Signals panel: remembered between visits.
  let open = false;
  try { open = localStorage.getItem('bn-signals') === '1'; } catch (e) {}
  function paintTog() {
    list.hidden = !open;
    tog.setAttribute('aria-expanded', String(open));
    tog.textContent = T(open ? 'Hide signals' : 'Show signals');
    if (open) BN_LIVE.paint();
  }
  tog.addEventListener('click', () => { open = !open; try { localStorage.setItem('bn-signals', open ? '1' : '0'); } catch (e) {} paintTog(); });
  paintTog();

  $('#cmRetry').addEventListener('click', () => {
    delete img.dataset.failed;
    if (window.BN_LIVE) { BN_LIVE.reconnect(); BN_LIVE.paint(); }
  });

  // -- full screen ----------------------------------------------------------- //
  const orient = () => window.Capacitor && Capacitor.isNativePlatform && Capacitor.isNativePlatform()
    && Capacitor.Plugins && Capacitor.Plugins.ScreenOrientation;
  let full = null;
  async function enter() {
    if (full) return;
    const phone = document.getElementById('phone');
    full = document.createElement('div');
    full.style.cssText = 'position:absolute;inset:0;z-index:70;background:#000';
    const native = orient();
    const inner = document.createElement('div');
    const W = phone.clientWidth, H = phone.clientHeight;
    inner.style.cssText = native
      ? 'position:absolute;inset:0'
      // Browser: a landscape box (H x W), turned a quarter so it fills the
      // portrait phone sideways.
      : `position:absolute;left:50%;top:50%;width:${H}px;height:${W}px;transform:translate(-50%,-50%) rotate(90deg)`;
    const close = document.createElement('button');
    close.type = 'button'; close.setAttribute('aria-label', T('Close full screen'));
    close.style.cssText = 'position:absolute;top:12px;right:12px;z-index:2;width:42px;height:42px;border:0;border-radius:50%;background:rgba(23,17,26,.7);color:#F4EFE6;display:grid;place-items:center';
    close.innerHTML = CLOSE;
    const chip = box.querySelector('[data-live="state-chip"]').cloneNode(true);
    chip.style.top = '12px'; chip.style.left = '12px';
    img.style.objectFit = 'contain';
    inner.append(img, chip, close);
    full.appendChild(inner);
    phone.appendChild(full);
    close.addEventListener('click', exit);
    if (native) { try { await orient().lock({ orientation: 'landscape' }); } catch (e) {} }
    BN_LIVE.paint();
  }
  async function exit() {
    if (!full) return;
    box.insertBefore(img, box.firstChild);
    full.remove(); full = null;
    if (orient()) { try { await orient().lock({ orientation: 'portrait' }); } catch (e) {} }
    BN_LIVE.paint();
  }
  $('#cmExpand').addEventListener('click', enter);
  // Leaving the screen while full screen: put everything back.
  const iv = setInterval(() => { if (!root.isConnected) { clearInterval(iv); if (full) { full.remove(); full = null; if (orient()) orient().lock({ orientation: 'portrait' }).catch(() => {}); } } }, 500);
};
