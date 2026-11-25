using System.Text.Json;

namespace EflNexus.Core.PendingJobs;

/// <summary>
/// WebView2 injected JavaScript payloads matching website_data_grabber.py 1:1.
/// </summary>
public static class PendingJobsScripts
{
    /// <summary>
    /// Exposes window.pywebview.api async Promise methods backed by CoreWebView2 host object "eflNexus".
    /// </summary>
    public static string BuildPyWebViewShimJs() => """
        (() => {
          const getHost = () => (window.chrome && window.chrome.webview && window.chrome.webview.hostObjects && window.chrome.webview.hostObjects.eflNexus) || null;
          window.pywebview = window.pywebview || {};
          window.pywebview.api = {
            save_job_ids: async (values) => {
              const h = getHost();
              if (!h || typeof h.save_job_ids_json !== 'function') throw new Error('Host unavailable');
              const res = await h.save_job_ids_json(JSON.stringify(values || []));
              return res ? JSON.parse(res) : { count: 0 };
            },
            lookup_warf_job: async (warfId) => {
              const h = getHost();
              if (!h || typeof h.lookup_warf_job_json !== 'function') return { job_id: '', gatepass: '', client: '' };
              const res = await h.lookup_warf_job_json(String(warfId || ''));
              return res ? JSON.parse(res) : { job_id: '', gatepass: '', client: '' };
            },
            save_downloaded_file: async (payload) => {
              const h = getHost();
              if (!h || typeof h.save_downloaded_file_json !== 'function') return { success: false, error: 'Host unavailable' };
              const res = await h.save_downloaded_file_json(JSON.stringify(payload || {}));
              return res ? JSON.parse(res) : { success: false, error: 'Empty response' };
            },
            request_loading_history: async (payload) => {
              const h = getHost();
              if (!h || typeof h.request_loading_history_json !== 'function') return { success: false, error: 'Host unavailable' };
              const res = await h.request_loading_history_json(JSON.stringify(payload || {}));
              return res ? JSON.parse(res) : { success: false, error: 'Empty response' };
            },
            get_pending_command: async () => {
              const h = getHost();
              if (!h || typeof h.get_pending_command_json !== 'function') return null;
              const res = await h.get_pending_command_json();
              return res ? JSON.parse(res) : null;
            },
            report_gatepass: async (val) => {
              const h = getHost();
              if (h && typeof h.report_gatepass === 'function') await h.report_gatepass(String(val || ''));
            },
            get_gatepass: async () => {
              const h = getHost();
              if (!h || typeof h.get_gatepass !== 'function') return '';
              return (await h.get_gatepass()) || '';
            },
            get_job_id: async () => {
              const h = getHost();
              if (!h || typeof h.get_job_id !== 'function') return '';
              return (await h.get_job_id()) || '';
            },
            get_client: async () => {
              const h = getHost();
              if (!h || typeof h.get_client !== 'function') return '';
              return (await h.get_client()) || '';
            }
          };
        })();
        """;

    public static string BuildInternalBrowserOverlayScript(string reconciliationUrl, int refreshSeconds)
    {
        var reconUrlJs = JsonSerializer.Serialize(
            string.IsNullOrWhiteSpace(reconciliationUrl) ? GrabberSettingsAndPaths.DefaultReconciliationUrl : reconciliationUrl);

        return $$"""
            (() => {
              if (window.__eflNexusPortalOverlay) return;
              window.__eflNexusPortalOverlay = true;
              const reconUrl = {{reconUrlJs}};

              const isInsideJob = () => {
                try {
                  const path = (location.pathname || '').toLowerCase();
                  const href = (location.href || '').toLowerCase();

                  if (path.includes('clerk-dashboard') || href.includes('clerk-dashboard') ||
                      href.includes('job_type=outbound') || href.includes('job_type=inbound')) {
                    try {
                      sessionStorage.removeItem('nexus_inside_job');
                      localStorage.removeItem('nexus_inside_job');
                    } catch (e) {}
                    return false;
                  }

                  if (path.includes('/warf') || href.includes('/warf')) return true;
                  if (path.includes('/job/') || path.includes('/jobs/') || href.includes('/job-details') || href.includes('/job_details') || href.includes('/reconciliation/start') || href.includes('/reconciliation/job')) return true;
                  if (/[?&]job_id=/i.test(href) || /[?&]job=[^&]+/i.test(href) || /[?&]warf_id=/i.test(href)) return true;

                  const headings = [...document.querySelectorAll('h1, h2, h3, h4, h5, .page-title, .card-title, header, .content-header')];
                  if (headings.some(h => {
                    const t = (h.textContent || '').toLowerCase();
                    return t.includes('job id -') || t.includes('job id:') || t.includes('job details') || t.includes('job start') || t.includes('warf start');
                  })) return true;

                  if (document.querySelector("form[action*='/warf'], form[action*='/job/'], input[name='job_id'], input[name='warf_id'], .job-details")) return true;

                  if (sessionStorage.getItem('nexus_inside_job') === '1' || localStorage.getItem('nexus_inside_job') === '1') return true;

                  return false;
                } catch (e) {
                  return false;
                }
              };

              const isJobDetailsPage = () => isInsideJob();

              const isReconciliationPage = () => {
                try {
                  if (isInsideJob()) return false;
                  const path = (location.pathname || '').toLowerCase();
                  const href = (location.href || '').toLowerCase();
                  if (path.includes('login') || path.includes('/warf')) return false;
                  if (path.includes('clerk-dashboard') || href.includes('clerk-dashboard') ||
                      href.includes('job_type=outbound') || href.includes('job_type=inbound') || href.includes('job_type=') ||
                      path.includes('pending') || href.includes('pending')) return true;
                  const allTables = [...document.querySelectorAll('table')];
                  return allTables.some(t => {
                    const txt = (t.textContent || '').toLowerCase().replace(/[^a-z0-9]/g, '');
                    if (txt.includes('jobid') || txt.includes('jobnumber') || txt.includes('jobno')) return true;
                    return /\b(?:out|in)_[a-z0-9_-]+/i.test(t.textContent || '');
                  });
                } catch (e) {
                  return false;
                }
              };

              const extractJobRecords = () => {
                const allTables = [...document.querySelectorAll('table')];
                const getHeaders = (table) => {
                  let ths = [...table.querySelectorAll('thead th')];
                  if (!ths.length) ths = [...table.querySelectorAll('tr th')];
                  if (!ths.length) {
                    const firstRow = table.querySelector('tr');
                    if (firstRow) ths = [...firstRow.querySelectorAll('th, td')];
                  }
                  return ths.map(h => h.textContent.trim().toLowerCase().replace(/[^a-z0-9]/g, ''));
                };
                let targetTable = null;
                let jobColIndex = -1;
                let clientColIndex = -1;
                let statusColIndex = -1;
                let whColIndex = -1;
                let gatepassColIndex = -1;
                let sealColIndex = -1;
                let deliveryColIndex = -1;
                for (const t of allTables) {
                  const headers = getHeaders(t);
                  let jIdx = headers.findIndex(h => ['jobid', 'jobnumber', 'jobno', 'job', 'job#'].includes(h) || h.includes('jobid'));
                  let rows = [...t.querySelectorAll('tbody tr')];
                  if (!rows.length) {
                    const allTrs = [...t.querySelectorAll('tr')];
                    rows = allTrs.length > 1 ? allTrs.slice(1) : allTrs;
                  }
                  if (jIdx < 0 && rows.length > 0) {
                    const sampleRows = rows.slice(0, 10);
                    const colMatches = {};
                    sampleRows.forEach(row => {
                      const cells = [...row.querySelectorAll('td, th')];
                      cells.forEach((cell, cIdx) => {
                        const val = cell.textContent.trim();
                        if (/\b(?:OUT|IN)_[A-Za-z0-9_-]+\b/i.test(val)) {
                          colMatches[cIdx] = (colMatches[cIdx] || 0) + 1;
                        }
                      });
                    });
                    const bestCol = Object.entries(colMatches).sort((a, b) => b[1] - a[1])[0];
                    if (bestCol && bestCol[1] > 0) {
                      jIdx = parseInt(bestCol[0], 10);
                    }
                  }
                  if (jIdx >= 0) {
                    targetTable = t;
                    jobColIndex = jIdx;
                    whColIndex = headers.findIndex(h => ['wh', 'warehouse', 'warehouseid', 'whid'].includes(h) || h === 'wh' || h.startsWith('wh'));
                    clientColIndex = headers.findIndex(h => ['client', 'customer', 'clientname', 'account', 'clientid'].includes(h) || h.includes('client'));
                    statusColIndex = headers.findIndex(h => ['reconciliationstatus', 'status', 'reconstatus', 'jobstatus', 'state'].includes(h) || h.includes('reconciliation') || h.includes('status'));
                    gatepassColIndex = headers.findIndex(h => ['gatepass', 'gatepassno', 'gatepassnumber', 'gatepassid', 'gp', 'gpno'].includes(h) || h.includes('gatepass'));
                    sealColIndex = headers.findIndex(h => ['sealnumber', 'sealno', 'seal', 'seal#'].includes(h) || h.includes('seal'));
                    deliveryColIndex = headers.findIndex(h => ['deliverylocation', 'delivery', 'destination', 'deliveryto'].includes(h) || h.includes('delivery'));
                    break;
                  }
                }
                if (!targetTable || jobColIndex < 0) return null;
                let rows = [...targetTable.querySelectorAll('tbody tr')];
                if (!rows.length) {
                  const allTrs = [...targetTable.querySelectorAll('tr')];
                  rows = allTrs.length > 1 ? allTrs.slice(1) : allTrs;
                }
                const values = [];
                for (const row of rows) {
                  const cells = row.querySelectorAll('td, th');
                  if (jobColIndex >= cells.length) continue;
                  const jobVal = cells[jobColIndex] ? cells[jobColIndex].textContent.trim() : '';
                  if (!jobVal) continue;
                  let clientVal = '';
                  if (clientColIndex >= 0 && clientColIndex < cells.length && cells[clientColIndex]) clientVal = cells[clientColIndex].textContent.trim();
                  let stVal = '';
                  if (statusColIndex >= 0 && statusColIndex < cells.length && cells[statusColIndex]) stVal = cells[statusColIndex].textContent.trim();
                  if (!stVal) {
                    const statusCell = [...cells].find(cell => /\b(?:pending|(?:on\s+|in\s+)?progress)\b/i.test(cell.textContent || ''));
                    if (statusCell) stVal = statusCell.textContent.trim();
                  }
                  let whVal = (whColIndex >= 0 && whColIndex < cells.length && cells[whColIndex]) ? cells[whColIndex].textContent.trim() : '';
                  let gatepassVal = (gatepassColIndex >= 0 && gatepassColIndex < cells.length && cells[gatepassColIndex]) ? cells[gatepassColIndex].textContent.trim() : '';
                  let sealVal = (sealColIndex >= 0 && sealColIndex < cells.length && cells[sealColIndex]) ? cells[sealColIndex].textContent.trim() : '';
                  let deliveryVal = (deliveryColIndex >= 0 && deliveryColIndex < cells.length && cells[deliveryColIndex]) ? cells[deliveryColIndex].textContent.trim() : '';
                  let warfId = '';
                  const warfForm = row.querySelector("form[action*='/warf/start'], a[href*='/warf/start'], form[action*='/warf/'], a[href*='/warf/'], form[action*='/warf']");
                  if (warfForm) {
                    const act = warfForm.getAttribute('action') || warfForm.getAttribute('href') || '';
                    const m = act.match(/\/warf\/(?:start\/)?(\d+)/i);
                    if (m && m[1]) warfId = m[1];
                  }
                  if (warfId && jobVal) {
                    try {
                      localStorage.setItem('nexus_warf_' + warfId, JSON.stringify({ job_id: jobVal, gatepass: gatepassVal, client: clientVal }));
                    } catch (e) {}
                  }
                  const startBtn = row.querySelector("button.btn-start, button[type='submit'], form button");
                  if (startBtn && !startBtn.hasAttribute('data-nexus-bound')) {
                    startBtn.setAttribute('data-nexus-bound', '1');
                    startBtn.addEventListener('click', () => {
                      try {
                        sessionStorage.setItem('nexus_inside_job', '1');
                        localStorage.setItem('nexus_inside_job', '1');
                        sessionStorage.setItem('nexus_active_job_id', jobVal);
                        sessionStorage.setItem('nexus_active_gatepass', gatepassVal);
                        sessionStorage.setItem('nexus_active_client', clientVal);
                        sessionStorage.setItem('nexus_active_warf_id', warfId);
                        localStorage.setItem('nexus_active_job_id', jobVal);
                        localStorage.setItem('nexus_active_gatepass', gatepassVal);
                        localStorage.setItem('nexus_active_client', clientVal);
                        localStorage.setItem('nexus_active_warf_id', warfId);
                      } catch (e) {}
                    });
                  }
                  const warfFormEl = row.querySelector("form[action*='/warf'], form");
                  if (warfFormEl && !warfFormEl.hasAttribute('data-nexus-bound-form')) {
                    warfFormEl.setAttribute('data-nexus-bound-form', '1');
                    warfFormEl.addEventListener('submit', () => {
                      try {
                        sessionStorage.setItem('nexus_inside_job', '1');
                        localStorage.setItem('nexus_inside_job', '1');
                      } catch (e) {}
                    });
                  }
                  values.push({
                    job_id: jobVal,
                    client: clientVal,
                    status: stVal,
                    warehouse: whVal,
                    gatepass: gatepassVal,
                    seal: sealVal,
                    delivery_location: deliveryVal,
                    warf_id: warfId
                  });
                }
                return values;
              };

              let lastExportSignature = '';
              let isExporting = false;
              let refreshInterval = {{refreshSeconds}};
              let refreshSeconds = refreshInterval;
              let autoRefreshPaused = refreshInterval <= 0;

              const autoExportJobIds = async (isManual = false) => {
                if (isExporting || !isReconciliationPage()) return false;
                if (!window.pywebview || !window.pywebview.api || typeof window.pywebview.api.save_job_ids !== 'function') {
                  if (isManual) alert('Connection to Tool 6 is initializing. Please wait a moment and click again.');
                  return false;
                }
                const records = extractJobRecords();
                if (!records) {
                  if (isManual) alert('No table with a recognizable Job ID column was found on this page.');
                  return false;
                }
                const signature = JSON.stringify(records);
                if (!isManual && signature === lastExportSignature) return true;
                isExporting = true;
                try {
                  const resp = await window.pywebview.api.save_job_ids(records);
                  lastExportSignature = signature;
                  const count = resp && resp.count !== undefined ? resp.count : records.length;
                  const btn = document.getElementById('efl-nexus-extract-job-ids');
                  if (btn) {
                    const syncLabel = (refreshInterval > 0) ? `Auto: ${refreshInterval}s` : 'Manual';
                    btn.textContent = `✓ Synced ${count} Jobs (${syncLabel})`;
                  }
                  return true;
                } catch (e) {
                  if (isManual) alert('Error sending Job IDs to Tool 6: ' + e);
                  return false;
                } finally {
                  isExporting = false;
                }
              };

              const DEFAULT_RECON_ZOOM = 0.80;
              let reconZoom = DEFAULT_RECON_ZOOM;
              try {
                const customVal = localStorage.getItem('nexus_recon_zoom_custom') || localStorage.getItem('nexus_recon_zoom');
                if (customVal !== null) {
                  const parsed = parseFloat(customVal);
                  if (!isNaN(parsed) && parsed >= 0.35 && parsed <= 1.5) {
                    reconZoom = Math.round(parsed * 100) / 100;
                  }
                }
              } catch (e) {
                reconZoom = DEFAULT_RECON_ZOOM;
              }

              const getPortalCss = (zoomVal) => `
                html { width: 100% !important; min-width: 0 !important; margin: 0 !important; padding: 0 !important; overflow-x: hidden !important; }
                body { zoom: ${zoomVal.toFixed(2)} !important; margin: 0 auto !important; padding: 4px 8px 48px 8px !important; width: 100% !important; max-width: 100% !important; min-width: 0 !important; box-sizing: border-box !important; overflow-x: hidden !important; }
                .container, .container-fluid, .content, main, .main-content, .content-wrapper, .page-content, .card, .wrapper, .app-content { margin-left: auto !important; margin-right: auto !important; max-width: 100% !important; width: 100% !important; box-sizing: border-box !important; float: none !important; }
                header, nav, .navbar, .navbar-nav, .nav, .nav-tabs { display: flex !important; flex-wrap: wrap !important; justify-content: center !important; align-items: center !important; max-width: 100% !important; gap: 2px 8px !important; }
                .nav-link, nav a, .navbar a, .navbar-brand { font-size: 11px !important; padding: 2px 4px !important; white-space: nowrap !important; }
                h1, h2, h3, h4, .page-title, .title { text-align: center !important; margin: 6px 0 !important; }
                .row, form, .filter-box, .filter-container, .filters { display: flex !important; flex-wrap: wrap !important; justify-content: center !important; align-items: center !important; margin-left: auto !important; margin-right: auto !important; margin-bottom: 6px !important; gap: 4px !important; float: none !important; max-width: 100% !important; }
                .table-responsive, .table-container { display: block !important; width: 100% !important; max-width: 100% !important; margin-left: auto !important; margin-right: auto !important; overflow-x: hidden !important; text-align: center !important; }
                table { margin-left: auto !important; margin-right: auto !important; float: none !important; display: table !important; width: 100% !important; max-width: 100% !important; border-collapse: collapse !important; table-layout: auto !important; }
                table th { white-space: normal !important; word-break: normal !important; overflow-wrap: break-word !important; text-align: center !important; vertical-align: middle !important; padding: 4px 3px !important; font-size: 10.5px !important; line-height: 1.15 !important; box-sizing: border-box !important; }
                table td { padding: 3px 4px !important; font-size: 11px !important; text-align: center !important; vertical-align: middle !important; box-sizing: border-box !important; white-space: nowrap !important; }
                table th:first-child, table td:first-child { width: 38px !important; max-width: 45px !important; }
                table th:last-child, table td:last-child { white-space: nowrap !important; text-align: center !important; width: auto !important; min-width: 75px !important; }
                table button.btn-start, table form[action*='/warf/start'] button, table td:last-child button, table td:last-child a.btn { white-space: nowrap !important; display: inline-block !important; visibility: visible !important; opacity: 1 !important; padding: 3px 8px !important; font-size: 11px !important; font-weight: 700 !important; cursor: pointer !important; }
              `;

              const ensurePortalStyle = () => {
                try {
                  let style = document.getElementById('efl-nexus-center-portal');
                  if (!style) {
                    style = document.createElement('style');
                    style.id = 'efl-nexus-center-portal';
                    style.setAttribute('data-zoom', reconZoom.toFixed(2));
                    style.textContent = getPortalCss(reconZoom);
                    const target = document.head || document.documentElement;
                    if (target) {
                      if (target.firstChild) target.insertBefore(style, target.firstChild);
                      else target.appendChild(style);
                    }
                  } else if (style.getAttribute('data-zoom') !== reconZoom.toFixed(2)) {
                    style.textContent = getPortalCss(reconZoom);
                    style.setAttribute('data-zoom', reconZoom.toFixed(2));
                  }
                  if (document.body && document.body.style.zoom !== reconZoom.toFixed(2)) {
                    document.body.style.setProperty('zoom', reconZoom.toFixed(2), 'important');
                  }
                } catch (e) {}
              };

              ensurePortalStyle();

              try {
                const instantObs = new MutationObserver(() => {
                  ensurePortalStyle();
                });
                instantObs.observe(document.documentElement, { childList: true, subtree: true });
              } catch (e) {}

              document.addEventListener('DOMContentLoaded', ensurePortalStyle);

              const applyReconZoom = () => {
                try {
                  ensurePortalStyle();
                  if (document.body) {
                    document.body.style.setProperty('zoom', reconZoom.toFixed(2), 'important');
                  }
                  const zoomLabel = document.getElementById('efl-nexus-zoom-level');
                  if (zoomLabel) {
                    zoomLabel.textContent = `${Math.round(reconZoom * 100)}%`;
                  }
                  const zoomWidget = document.getElementById('efl-nexus-zoom-widget');
                  if (zoomWidget) zoomWidget.style.display = (isReconciliationPage() || isInsideJob()) ? 'flex' : 'none';
                } catch (e) {}
              };

              const setReconZoom = (newZoom) => {
                reconZoom = Math.min(Math.max(Math.round(newZoom * 100) / 100, 0.35), 1.5);
                try {
                  localStorage.setItem('nexus_recon_zoom_custom', reconZoom.toFixed(2));
                  localStorage.setItem('nexus_recon_zoom', reconZoom.toFixed(2));
                } catch (e) {}
                ensurePortalStyle();
                applyReconZoom();
              };

              const resetReconZoom = () => {
                reconZoom = DEFAULT_RECON_ZOOM;
                try {
                  localStorage.removeItem('nexus_recon_zoom_custom');
                  localStorage.setItem('nexus_recon_zoom', DEFAULT_RECON_ZOOM.toFixed(2));
                } catch (e) {}
                ensurePortalStyle();
                applyReconZoom();
              };

              window.addEventListener('keydown', (e) => {
                if (!e.ctrlKey && !e.metaKey) return;
                if (e.key === '=' || e.key === '+' || e.keyCode === 187 || e.keyCode === 107) { e.preventDefault(); setReconZoom(reconZoom + 0.05); }
                else if (e.key === '-' || e.key === '_' || e.keyCode === 189 || e.keyCode === 109) { e.preventDefault(); setReconZoom(reconZoom - 0.05); }
                else if (e.key === '0' || e.keyCode === 96 || e.keyCode === 48) { e.preventDefault(); resetReconZoom(); }
              }, { passive: false });

              window.addEventListener('wheel', (e) => {
                if (!e.ctrlKey && !e.metaKey) return;
                e.preventDefault();
                if (e.deltaY < 0) setReconZoom(reconZoom + 0.05);
                else if (e.deltaY > 0) setReconZoom(reconZoom - 0.05);
              }, { passive: false });

              const centerPortal = () => {
                try {
                  ensurePortalStyle();
                  document.querySelectorAll('table').forEach(t => {
                    t.style.marginLeft = 'auto';
                    t.style.marginRight = 'auto';
                    t.style.float = 'none';
                    t.style.display = 'table';
                    t.style.width = '100%';
                    t.style.maxWidth = '100%';
                    if (t.parentElement) {
                      t.parentElement.style.marginLeft = 'auto';
                      t.parentElement.style.marginRight = 'auto';
                      if (t.parentElement.classList.contains('table-responsive')) {
                        t.parentElement.style.display = 'block';
                        t.parentElement.style.width = '100%';
                        t.parentElement.style.overflowX = 'hidden';
                        t.parentElement.style.textAlign = 'center';
                      }
                    }
                  });
                  document.querySelectorAll('.container, .container-fluid, .row, form').forEach(c => {
                    c.style.marginLeft = 'auto'; c.style.marginRight = 'auto'; c.style.float = 'none';
                  });
                  applyReconZoom();
                } catch (e) {}
              };
              centerPortal();
              window.addEventListener('resize', centerPortal);
              setInterval(centerPortal, 750);
              try {
                const domObs = new MutationObserver(() => { centerPortal(); });
                if (document.body) domObs.observe(document.body, { childList: true, subtree: true });
              } catch (e) {}

              const attachButton = () => {
                if (document.getElementById('efl-nexus-extract-job-ids')) return;
                const button = document.createElement('button');
                button.id = 'efl-nexus-extract-job-ids';
                button.type = 'button';
                button.textContent = (refreshInterval > 0) ? `Auto-Sync: ${refreshInterval}s | Export Job IDs` : 'Auto-Sync: Off | Export Job IDs';
                Object.assign(button.style, {
                  position: 'fixed', right: '16px', bottom: '8px', zIndex: 2147483647,
                  border: '0', borderRadius: '5px', padding: '6px 12px', cursor: 'pointer',
                  background: '#0d1b2a', color: '#ffffff', fontWeight: '700', fontSize: '11px',
                  boxShadow: '0 2px 8px rgba(0,0,0,0.3)', opacity: '0.88', transition: 'opacity 0.2s, background 0.2s'
                });
                button.onmouseenter = () => { button.style.opacity = '1'; };
                button.onmouseleave = () => { button.style.opacity = '0.88'; };
                button.addEventListener('click', () => autoExportJobIds(true));
                const p = document.body || document.documentElement;
                if (p) p.appendChild(button);
              };
              attachButton();
              setInterval(attachButton, 1000);

              const pollAutoExport = () => { if (!isInsideJob() && isReconciliationPage()) autoExportJobIds(false); };
              setInterval(pollAutoExport, 1500);
              setTimeout(pollAutoExport, 500);
              setTimeout(pollAutoExport, 1000);

              const tickCountdown = () => {
                if (isInsideJob() || !isReconciliationPage() || autoRefreshPaused || refreshInterval <= 0) {
                  refreshSeconds = refreshInterval;
                  const btn = document.getElementById('efl-nexus-extract-job-ids');
                  if (btn) {
                    if (isInsideJob()) {
                      btn.style.display = 'block';
                      btn.textContent = '⏸ Auto-Refresh Paused (Inside Job)';
                      btn.style.background = '#eab308';
                      btn.style.color = '#000000';
                    } else if (!isReconciliationPage()) {
                      btn.style.display = 'none';
                    } else {
                      btn.style.display = 'block';
                      btn.textContent = 'Auto-Sync: Off | Export Job IDs';
                      btn.style.background = '#0d1b2a';
                      btn.style.color = '#ffffff';
                    }
                  }
                  return;
                }
                const btn = document.getElementById('efl-nexus-extract-job-ids');
                if (btn) {
                  btn.style.display = 'block';
                  btn.style.background = '#0d1b2a';
                  btn.style.color = '#ffffff';
                }
                refreshSeconds--;
                if (btn && refreshSeconds > 0) btn.textContent = `Auto-Sync Active (Refresh in ${refreshSeconds}s)`;
                if (refreshSeconds <= 0) {
                  refreshSeconds = refreshInterval;
                  if (btn) btn.textContent = 'Refreshing...';
                  autoExportJobIds(false).finally(() => {
                    if (!isInsideJob() && isReconciliationPage() && !autoRefreshPaused && refreshInterval > 0) location.reload();
                  });
                }
              };
              setInterval(tickCountdown, 1000);

              const attachBackButton = () => {
                if (document.getElementById('efl-nexus-go-back')) return;
                const backBtn = document.createElement('button');
                backBtn.id = 'efl-nexus-go-back';
                backBtn.type = 'button';
                backBtn.textContent = '◀ Go Back';
                Object.assign(backBtn.style, {
                  position: 'fixed', left: '16px', bottom: '8px', zIndex: 2147483647,
                  border: '0', borderRadius: '5px', padding: '6px 12px', cursor: 'pointer',
                  background: '#0d1b2a', color: '#ffffff', fontWeight: '700', fontSize: '11px',
                  boxShadow: '0 2px 8px rgba(0,0,0,0.3)', opacity: '0.88', transition: 'opacity 0.2s, background 0.2s'
                });
                backBtn.onmouseenter = () => { backBtn.style.opacity = '1'; };
                backBtn.onmouseleave = () => { backBtn.style.opacity = '0.88'; };
                backBtn.addEventListener('click', () => {
                  try {
                    sessionStorage.removeItem('nexus_inside_job');
                    localStorage.removeItem('nexus_inside_job');
                  } catch (e) {}
                  if (window.history.length > 1) window.history.back();
                  else location.assign(reconUrl);
                });
                const p = document.body || document.documentElement;
                if (p) p.appendChild(backBtn);
              };
              attachBackButton();
              setInterval(attachBackButton, 1000);

              const attachZoomControls = () => {
                if (document.getElementById('efl-nexus-zoom-widget')) return;
                const widget = document.createElement('div');
                widget.id = 'efl-nexus-zoom-widget';
                Object.assign(widget.style, {
                  position: 'fixed', left: '105px', bottom: '8px', zIndex: 2147483647,
                  display: (isReconciliationPage() || isInsideJob()) ? 'flex' : 'none', alignItems: 'center', gap: '4px',
                  background: '#0d1b2a', borderRadius: '5px', padding: '4px 8px',
                  boxShadow: '0 2px 8px rgba(0,0,0,0.3)', opacity: '0.88',
                  fontFamily: 'Segoe UI, sans-serif', fontSize: '11px', fontWeight: '700',
                  color: '#ffffff', userSelect: 'none', transition: 'opacity 0.2s'
                });
                widget.onmouseenter = () => { widget.style.opacity = '1'; };
                widget.onmouseleave = () => { widget.style.opacity = '0.88'; };

                const btnMinus = document.createElement('button');
                btnMinus.type = 'button'; btnMinus.textContent = '−'; btnMinus.title = 'Zoom Out (Ctrl + -)';
                Object.assign(btnMinus.style, { background: '#1b2a4a', color: '#fff', border: '0', borderRadius: '3px', width: '18px', height: '18px', cursor: 'pointer', fontWeight: 'bold', fontSize: '13px', lineHeight: '1', display: 'flex', alignItems: 'center', justifyContent: 'center' });
                btnMinus.onclick = () => setReconZoom(reconZoom - 0.05);

                const label = document.createElement('span');
                label.id = 'efl-nexus-zoom-level';
                label.textContent = `${Math.round(reconZoom * 100)}%`;
                label.title = 'Current Zoom (Click to Reset to 80% | Ctrl + 0)';
                Object.assign(label.style, { padding: '0 4px', cursor: 'pointer', minWidth: '32px', textAlign: 'center' });
                label.onclick = () => resetReconZoom();

                const btnPlus = document.createElement('button');
                btnPlus.type = 'button'; btnPlus.textContent = '+'; btnPlus.title = 'Zoom In (Ctrl + +)';
                Object.assign(btnPlus.style, { background: '#1b2a4a', color: '#fff', border: '0', borderRadius: '3px', width: '18px', height: '18px', cursor: 'pointer', fontWeight: 'bold', fontSize: '13px', lineHeight: '1', display: 'flex', alignItems: 'center', justifyContent: 'center' });
                btnPlus.onclick = () => setReconZoom(reconZoom + 0.05);

                widget.appendChild(btnMinus); widget.appendChild(label); widget.appendChild(btnPlus);
                const pWidget = document.body || document.documentElement;
                if (pWidget) pWidget.appendChild(widget);
              };
              attachZoomControls();
              setInterval(attachZoomControls, 1000);

              window.__nexusJobContext = window.__nexusJobContext || { job_id: '', gatepass: '', client: '' };

              const getCurrentJobId = () => {
                if (window.__nexusJobContext && window.__nexusJobContext.job_id) {
                  const c = String(window.__nexusJobContext.job_id).trim();
                  if (!/^\d+$/.test(c)) return c;
                }
                try {
                  const bodyText = document.body ? (document.body.innerText || '') : '';
                  const directMatch = bodyText.match(/\b((?:OUT|IN)_[A-Za-z0-9_-]+)\b/i);
                  if (directMatch && directMatch[1]) return directMatch[1].trim();
                  const candidateElements = [...document.querySelectorAll('h1, h2, h3, h4, h5, header, .card-title, [class*="header"], strong, b, .badge, .breadcrumb, div, span, p, td, th')];
                  for (const el of candidateElements) {
                    const txt = (el.textContent || '').trim();
                    const m = txt.match(/Job\s*ID\s*[-:]\s*([A-Za-z0-9_-]+)/i) || txt.match(/Job\s*(?:No|Number|#)\s*[-:]\s*([A-Za-z0-9_-]+)/i);
                    if (m && m[1] && !/^\d+$/.test(m[1].trim())) return m[1].trim();
                  }
                  const saved = sessionStorage.getItem('nexus_active_job_id') || localStorage.getItem('nexus_active_job_id');
                  if (saved && !/^\d+$/.test(saved)) return saved;
                  const m = (location.pathname || '').match(/\/warf\/(?:start\/)?([^\/?#]+)/i);
                  if (m && m[1]) {
                    const warfData = localStorage.getItem('nexus_warf_' + m[1]);
                    if (warfData) {
                      try { const parsed = JSON.parse(warfData); if (parsed && parsed.job_id && !/^\d+$/.test(parsed.job_id)) return parsed.job_id; } catch (e) {}
                    }
                    return m[1];
                  }
                } catch (e) {}
                return '';
              };

              const getCurrentGatepass = () => {
                if (window.__nexusJobContext && window.__nexusJobContext.gatepass) return window.__nexusJobContext.gatepass;
                try {
                  const m = (location.pathname || '').match(/\/warf\/(?:start\/)?([^\/?#]+)/i);
                  if (m && m[1]) {
                    const warfData = localStorage.getItem('nexus_warf_' + m[1]);
                    if (warfData) { try { const parsed = JSON.parse(warfData); if (parsed && parsed.gatepass) return parsed.gatepass; } catch (e) {} }
                  }
                  const ths = [...document.querySelectorAll('th, td, label, dt')];
                  for (let i = 0; i < ths.length; i++) {
                    const txt = (ths[i].textContent || '').trim();
                    if (/^(?:Gate\s*Pass(?:\s*No|\s*ID|\s*Number)?|Gatepass(?:\s*No|\s*ID|\s*Number)?)$/i.test(txt)) {
                      const next = ths[i].nextElementSibling;
                      if (next && next.textContent.trim()) return next.textContent.trim();
                    }
                  }
                  for (const el of document.querySelectorAll('h1, h2, h3, h4, h5, div, span, p, td, tr')) {
                    const m2 = (el.textContent || '').match(/Gate\s*Pass(?:\s*No|\s*ID|\s*Number)?\s*[-:#]?\s*([A-Za-z0-9_-]+)/i);
                    if (m2 && m2[1]) return m2[1].trim();
                  }
                  const saved = sessionStorage.getItem('nexus_active_gatepass') || localStorage.getItem('nexus_active_gatepass');
                  if (saved) return saved;
                } catch (e) {}
                return '';
              };

              const getCurrentClient = () => {
                if (window.__nexusJobContext && window.__nexusJobContext.client) return window.__nexusJobContext.client;
                try {
                  const m = (location.pathname || '').match(/\/warf\/(?:start\/)?([^\/?#]+)/i);
                  if (m && m[1]) {
                    const warfData = localStorage.getItem('nexus_warf_' + m[1]);
                    if (warfData) { try { const parsed = JSON.parse(warfData); if (parsed && parsed.client) return parsed.client; } catch (e) {} }
                  }
                  for (const el of document.querySelectorAll('h1, h2, h3, h4, h5, div, span, p, td, tr')) {
                    const m2 = (el.textContent || '').match(/(?:Client|Customer)(?:\s*Name)?\s*[-:]\s*([A-Za-z0-9_-]+)/i);
                    if (m2 && m2[1]) return m2[1].trim();
                  }
                  const saved = sessionStorage.getItem('nexus_active_client') || localStorage.getItem('nexus_active_client');
                  if (saved) return saved;
                } catch (e) {}
                return '';
              };

              const showDownloadToast = (msg, isError = false) => {
                try {
                  let toast = document.getElementById('efl-nexus-download-toast');
                  if (!toast) {
                    toast = document.createElement('div');
                    toast.id = 'efl-nexus-download-toast';
                    Object.assign(toast.style, {
                      position: 'fixed', top: '20px', right: '20px', zIndex: '2147483647',
                      padding: '12px 20px', borderRadius: '8px', color: '#ffffff',
                      fontWeight: '700', fontSize: '13px', boxShadow: '0 4px 18px rgba(0,0,0,0.3)',
                      transition: 'opacity 0.3s, transform 0.3s', maxWidth: '480px', wordBreak: 'break-word'
                    });
                    if (document.body) document.body.appendChild(toast);
                  }
                  toast.style.background = isError ? '#dc2626' : '#16a34a';
                  toast.textContent = msg; toast.style.display = 'block'; toast.style.opacity = '1'; toast.style.transform = 'translateY(0)';
                  clearTimeout(toast._timeout);
                  toast._timeout = setTimeout(() => {
                    toast.style.opacity = '0'; toast.style.transform = 'translateY(-10px)';
                    setTimeout(() => { if (toast.style.opacity === '0') toast.style.display = 'none'; }, 300);
                  }, 4000);
                } catch (e) {}
              };

              let reconciliationReturnTimer = null;
              const scheduleReturnToReconciliation = () => {
                if (reconciliationReturnTimer) clearTimeout(reconciliationReturnTimer);
                showDownloadToast('Download saved. Returning to Reconciliation in 5 seconds...');
                reconciliationReturnTimer = setTimeout(() => { location.assign(reconUrl); }, 5000);
              };

              const fetchAndSaveFile = async (url, suggestedName, statusEl = null, returnAfterSuccess = false, excelOnly = false) => {
                if (!window.pywebview || !window.pywebview.api || typeof window.pywebview.api.save_downloaded_file !== 'function') {
                  showDownloadToast('Connection initializing... please click again in a moment.', true);
                  return false;
                }
                const originalText = statusEl ? statusEl.textContent : '';
                if (statusEl) { statusEl.textContent = '⏳ Downloading...'; statusEl.disabled = true; }
                showDownloadToast('Downloading: ' + (suggestedName || 'file') + '...');
                try {
                  const response = await fetch(url, { credentials: 'include' });
                  if (!response.ok) throw new Error('HTTP ' + response.status + ': ' + response.statusText);
                  if (excelOnly) {
                    const mime = (response.headers.get('content-type') || '').split(';')[0].trim().toLowerCase();
                    const excelMime = /^(application\/(vnd\.ms-excel(?:\.[a-z0-9.-]+)?|vnd\.openxmlformats-officedocument\.spreadsheetml\.(sheet|template)))$/i;
                    if (mime && mime !== 'application/octet-stream' && !excelMime.test(mime)) {
                      if (response.body) await response.body.cancel();
                      throw new Error('Skipped non-Excel response: ' + mime);
                    }
                  }
                  const blob = await response.blob();
                  return new Promise((resolve) => {
                    const reader = new FileReader();
                    reader.onloadend = async () => {
                      try {
                        const base64Data = reader.result;
                        let activeJob = getCurrentJobId();
                        let activeGp = getCurrentGatepass();
                        let activeCli = getCurrentClient();
                        if (/^\d+$/.test(activeJob) && window.pywebview && window.pywebview.api && typeof window.pywebview.api.lookup_warf_job === 'function') {
                          try {
                            const mapped = await window.pywebview.api.lookup_warf_job(activeJob);
                            if (mapped && mapped.job_id) {
                              activeJob = mapped.job_id;
                              if (!activeGp) activeGp = mapped.gatepass || '';
                              if (!activeCli) activeCli = mapped.client || '';
                            }
                          } catch (e) {}
                        }
                        const result = await window.pywebview.api.save_downloaded_file({
                          filename: suggestedName || url.split('/').pop().split('?')[0] || 'downloaded_file',
                          data: base64Data, url: url, job_id: activeJob, gatepass: activeGp, client: activeCli
                        });
                        if (result && result.success) {
                          const locName = result.folder ? 'folder ' + result.folder : 'Downloads folder';
                          showDownloadToast('✓ Saved: ' + result.filename + ' in ' + locName + '!');
                          if (statusEl) statusEl.textContent = '✓ Downloaded';
                          if (returnAfterSuccess) scheduleReturnToReconciliation();
                          resolve(result);
                        } else {
                          throw new Error(result && result.error ? result.error : 'Save failed');
                        }
                      } catch (err) {
                        showDownloadToast('Save failed: ' + err.message, true);
                        if (statusEl) statusEl.textContent = originalText;
                        resolve(false);
                      } finally {
                        if (statusEl) { statusEl.disabled = false; setTimeout(() => { statusEl.textContent = originalText; }, 3500); }
                      }
                    };
                    reader.onerror = () => {
                      showDownloadToast('Failed to read file response', true);
                      if (statusEl) { statusEl.textContent = originalText; statusEl.disabled = false; }
                      resolve(false);
                    };
                    reader.readAsDataURL(blob);
                  });
                } catch (err) {
                  showDownloadToast('Download error: ' + err.message, true);
                  if (statusEl) { statusEl.textContent = originalText; statusEl.disabled = false; }
                  return false;
                }
              };

              const isDownloadableLink = (el) => {
                if (!el || el.tagName !== 'A') return false;
                if (el.classList.contains('btn-download') || el.hasAttribute('download')) return true;
                const href = (el.getAttribute('href') || '').toLowerCase();
                if (!href || href.startsWith('#') || href.startsWith('javascript:')) return false;
                const fileExts = ['.xlsx', '.xls', '.csv', '.pdf', '.docx', '.doc', '.zip', '.png', '.jpg', '.jpeg'];
                return fileExts.some(ext => href.includes(ext)) || href.includes('/storage/app/public/uploads/');
              };

              document.addEventListener('click', (e) => {
                const link = e.target && e.target.closest ? e.target.closest('a') : null;
                if (link && isDownloadableLink(link)) {
                  e.preventDefault(); e.stopPropagation();
                  const url = link.href || link.getAttribute('href');
                  const filename = link.getAttribute('download') || link.textContent.trim() || url.split('/').pop().split('?')[0];
                  fetchAndSaveFile(url, filename, link, true);
                }
              }, true);

              const enhanceEvidenceCards = () => {
                document.querySelectorAll('.evidence-card:not([data-nexus-enhanced])').forEach(card => {
                  card.setAttribute('data-nexus-enhanced', '1');
                  const imgUrl = card.getAttribute('data-img');
                  if (!imgUrl) return;
                  const dlBtn = document.createElement('button');
                  dlBtn.type = 'button'; dlBtn.textContent = '💾 Save Image';
                  Object.assign(dlBtn.style, {
                    marginTop: '6px', width: '100%', fontSize: '11px', padding: '3px 6px',
                    background: '#f08b08', color: '#ffffff', border: 'none', borderRadius: '4px', cursor: 'pointer', fontWeight: 'bold'
                  });
                  dlBtn.addEventListener('click', (ev) => {
                    ev.preventDefault(); ev.stopPropagation();
                    const stack = card.getAttribute('data-stack') || 'evidence';
                    const filename = `Job_${getCurrentJobId() || 'job'}_Stack_${stack}_${imgUrl.split('/').pop().split('?')[0]}`;
                    fetchAndSaveFile(imgUrl, filename, dlBtn, true);
                  });
                  card.appendChild(dlBtn);
                });

                const modal = document.getElementById('imageModal');
                if (modal && !document.getElementById('efl-nexus-modal-dl-btn')) {
                  const modalHeader = modal.querySelector('.modal-header');
                  if (modalHeader) {
                    const modalDlBtn = document.createElement('button');
                    modalDlBtn.id = 'efl-nexus-modal-dl-btn'; modalDlBtn.type = 'button';
                    modalDlBtn.className = 'btn btn-sm btn-warning me-2'; modalDlBtn.textContent = '💾 Download Image';
                    modalDlBtn.addEventListener('click', () => {
                      const modalImg = document.getElementById('modalImage');
                      if (modalImg && modalImg.src) {
                        const stack = document.getElementById('modalStack')?.textContent || '';
                        const filename = `Job_${getCurrentJobId() || 'job'}_${stack.replace(/[^a-z0-9]/gi, '_')}_evidence.jpg`;
                        fetchAndSaveFile(modalImg.src, filename, modalDlBtn, true);
                      }
                    });
                    const closeBtn = modalHeader.querySelector('.btn-close');
                    if (closeBtn) modalHeader.insertBefore(modalDlBtn, closeBtn);
                    else modalHeader.appendChild(modalDlBtn);
                  }
                }
              };
              setInterval(enhanceEvidenceCards, 1000);

              const getExcelDownloadName = (href, downloadName, label) => {
                const excelExtension = /\.(xlsx|xls|xlsm|xlsb|xltx|xltm|xlt)$/i;
                let urlName;
                try { urlName = decodeURIComponent(new URL(href).pathname.split('/').pop()); }
                catch (e) { return ''; }
                if (/\.[a-z0-9]+$/i.test(urlName) && !excelExtension.test(urlName)) return '';
                return [urlName, downloadName, label].find(candidate => excelExtension.test(candidate)) || '';
              };

              const getAllJobDownloadItems = () => {
                const items = [];
                document.querySelectorAll("a.btn-download, a[download], table a[href*='/storage/'], table a[href*='uploads']").forEach(l => {
                  const href = l.href || l.getAttribute('href');
                  if (href && !items.some(it => it.url === href)) {
                    const name = getExcelDownloadName(href, l.getAttribute('download') || '', l.textContent.trim());
                    if (name) items.push({ url: href, filename: name });
                  }
                });
                return items;
              };

              const downloadAllJobFiles = async (returnAfterSuccess = false) => {
                const items = getAllJobDownloadItems();
                if (!items.length) { showDownloadToast('No Excel sheets found on this page.', true); return; }
                showDownloadToast('Starting download of ' + items.length + ' file(s)...');
                const allBtn = document.getElementById('efl-nexus-download-all');
                if (allBtn) { allBtn.disabled = true; allBtn.textContent = '⏳ Downloading (0/' + items.length + ')...'; }
                let successCount = 0; let lastFolder = '';
                for (let i = 0; i < items.length; i++) {
                  if (allBtn) allBtn.textContent = '⏳ Downloading (' + (i + 1) + '/' + items.length + ')...';
                  const res = await fetchAndSaveFile(items[i].url, items[i].filename, null, false, true);
                  if (res) { successCount++; if (res.folder) lastFolder = res.folder; }
                }
                if (allBtn) {
                  allBtn.disabled = false; allBtn.textContent = '✓ Downloaded ' + successCount + '/' + items.length + ' Files';
                  setTimeout(() => { allBtn.textContent = '📥 Download All Excel Sheets'; }, 4000);
                }
                const destMsg = lastFolder ? 'folder ' + lastFolder : 'Downloads folder';
                showDownloadToast('✓ Finished: ' + successCount + ' of ' + items.length + ' file(s) saved to ' + destMsg + '!');
                if (returnAfterSuccess && successCount > 0) scheduleReturnToReconciliation();
              };

              const getJobDownloadToolbar = () => {
                let toolbar = document.getElementById('efl-nexus-job-download-toolbar');
                if (!toolbar && document.body) {
                  toolbar = document.createElement('div');
                  toolbar.id = 'efl-nexus-job-download-toolbar';
                  Object.assign(toolbar.style, {
                    position: 'fixed', left: '105px', bottom: '8px', zIndex: 2147483647,
                    display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '10px',
                    maxWidth: 'calc(100vw - 121px)'
                  });
                  document.body.appendChild(toolbar);
                }
                if (toolbar) toolbar.style.display = isJobDetailsPage() ? 'flex' : 'none';
                return toolbar;
              };

              const attachDownloadAllButton = () => {
                const toolbar = getJobDownloadToolbar();
                if (!isJobDetailsPage()) {
                  const btn = document.getElementById('efl-nexus-download-all');
                  if (btn) btn.style.display = 'none';
                  return;
                }
                let btn = document.getElementById('efl-nexus-download-all');
                if (!btn) {
                  btn = document.createElement('button');
                  btn.id = 'efl-nexus-download-all'; btn.type = 'button'; btn.textContent = '📥 Download All Excel Sheets';
                  Object.assign(btn.style, {
                    flex: '0 0 auto', maxWidth: '100%', whiteSpace: 'normal', border: '0', borderRadius: '5px',
                    padding: '6px 12px', cursor: 'pointer', background: '#16a34a', color: '#ffffff',
                    fontWeight: '700', fontSize: '11px', boxShadow: '0 2px 8px rgba(0,0,0,0.3)', opacity: '0.9', transition: 'opacity 0.2s, background 0.2s'
                  });
                  btn.onmouseenter = () => { btn.style.opacity = '1'; };
                  btn.onmouseleave = () => { btn.style.opacity = '0.9'; };
                  btn.addEventListener('click', () => downloadAllJobFiles(true));
                  if (toolbar) toolbar.appendChild(btn);
                } else { btn.style.display = 'block'; }
              };
              attachDownloadAllButton();
              setInterval(attachDownloadAllButton, 1000);

              const getActiveJobType = () => {
                const id = (getCurrentJobId() || '').trim().toUpperCase();
                if (id.startsWith('OUT')) return 'OUT';
                if (id.startsWith('IN')) return 'IN';
                const saved = (sessionStorage.getItem('nexus_active_job_id') || localStorage.getItem('nexus_active_job_id') || '').trim().toUpperCase();
                if (saved.startsWith('OUT')) return 'OUT';
                if (saved.startsWith('IN')) return 'IN';
                const href = (location.href || '').toLowerCase();
                if (href.includes('job_type=outbound') || href.includes('outbound')) return 'OUT';
                if (href.includes('job_type=inbound') || href.includes('inbound')) return 'IN';
                const bodyText = document.body ? (document.body.innerText || '') : '';
                if (/\bOUT_[A-Za-z0-9_-]+/i.test(bodyText)) return 'OUT';
                if (/\bIN_[A-Za-z0-9_-]+/i.test(bodyText)) return 'IN';
                return 'OUT';
              };

              const attachJobReportButtons = () => {
                const toolbar = getJobDownloadToolbar();
                let outBtn = document.getElementById('efl-nexus-loading-history');
                let inBtn = document.getElementById('efl-nexus-inventory-gatepass');
                if (!isJobDetailsPage()) {
                  if (outBtn) outBtn.style.display = 'none';
                  if (inBtn) inBtn.style.display = 'none';
                  return;
                }
                const jobType = getActiveJobType();
                if (jobType === 'OUT') {
                  if (inBtn) inBtn.style.display = 'none';
                  if (!outBtn) {
                    outBtn = document.createElement('button');
                    outBtn.id = 'efl-nexus-loading-history';
                    outBtn.type = 'button';
                    outBtn.textContent = 'Download Loading History';
                    Object.assign(outBtn.style, {
                      flex: '0 0 auto', maxWidth: '100%', whiteSpace: 'normal', border: '0', borderRadius: '5px',
                      padding: '6px 12px', cursor: 'pointer', background: '#2563eb', color: '#ffffff',
                      fontWeight: '700', fontSize: '11px', boxShadow: '0 2px 8px rgba(0,0,0,0.3)', opacity: '0.9',
                      transition: 'opacity 0.2s, background 0.2s'
                    });
                    outBtn.onmouseenter = () => { outBtn.style.opacity = '1'; };
                    outBtn.onmouseleave = () => { outBtn.style.opacity = '0.9'; };
                    outBtn.addEventListener('click', async () => {
                      if (!window.pywebview || !window.pywebview.api || typeof window.pywebview.api.request_loading_history !== 'function') {
                        showDownloadToast('Connection initializing... please try again.', true);
                        return;
                      }
                      outBtn.disabled = true;
                      try {
                        const activeGp = getCurrentGatepass();
                        const result = await window.pywebview.api.request_loading_history({
                          job_id: getCurrentJobId(),
                          gatepass: activeGp,
                          client: getCurrentClient(),
                          page_code: '1992',
                          report_name: 'Loading History Report'
                        });
                        if (result && result.success) {
                          const gpMsg = activeGp ? ' for Gate Pass ' + activeGp : '';
                          showDownloadToast('Querying and exporting Loading History' + gpMsg + '...');
                        } else showDownloadToast('Could not open Loading History.', true);
                      } catch (e) {
                        showDownloadToast('Could not open Loading History.', true);
                      } finally { outBtn.disabled = false; }
                    });
                    if (toolbar) toolbar.appendChild(outBtn);
                  } else { outBtn.style.display = 'block'; }
                } else {
                  if (outBtn) outBtn.style.display = 'none';
                  if (!inBtn) {
                    inBtn = document.createElement('button');
                    inBtn.id = 'efl-nexus-inventory-gatepass';
                    inBtn.type = 'button';
                    inBtn.textContent = 'Download Inventory by Gatepass';
                    Object.assign(inBtn.style, {
                      flex: '0 0 auto', maxWidth: '100%', whiteSpace: 'normal', border: '0', borderRadius: '5px',
                      padding: '6px 12px', cursor: 'pointer', background: '#7c3aed', color: '#ffffff',
                      fontWeight: '700', fontSize: '11px', boxShadow: '0 2px 8px rgba(0,0,0,0.3)', opacity: '0.9',
                      transition: 'opacity 0.2s, background 0.2s'
                    });
                    inBtn.onmouseenter = () => { inBtn.style.opacity = '1'; };
                    inBtn.onmouseleave = () => { inBtn.style.opacity = '0.9'; };
                    inBtn.addEventListener('click', async () => {
                      if (!window.pywebview || !window.pywebview.api || typeof window.pywebview.api.request_loading_history !== 'function') {
                        showDownloadToast('Connection initializing... please try again.', true);
                        return;
                      }
                      inBtn.disabled = true;
                      try {
                        const activeGp = getCurrentGatepass();
                        const result = await window.pywebview.api.request_loading_history({
                          job_id: getCurrentJobId(),
                          gatepass: activeGp,
                          client: getCurrentClient(),
                          page_code: '2598',
                          report_name: 'Inventory by gatepass'
                        });
                        if (result && result.success) {
                          const gpMsg = activeGp ? ' for Gate Pass ' + activeGp : '';
                          showDownloadToast('Querying and exporting Inventory by Gatepass' + gpMsg + '...');
                        } else showDownloadToast('Could not open Inventory by Gatepass.', true);
                      } catch (e) {
                        showDownloadToast('Could not open Inventory by Gatepass.', true);
                      } finally { inBtn.disabled = false; }
                    });
                    if (toolbar) toolbar.appendChild(inBtn);
                  } else { inBtn.style.display = 'block'; }
                }
              };
              attachJobReportButtons();
              setInterval(attachJobReportButtons, 1000);

              const executeStartJob = (jobId) => {
                const targetClean = String(jobId || '').trim().toLowerCase().replace(/[^a-z0-9]/g, '');
                if (!targetClean) return;
                try {
                  sessionStorage.setItem('nexus_inside_job', '1');
                  localStorage.setItem('nexus_inside_job', '1');
                } catch (e) {}
                for (const table of document.querySelectorAll('table')) {
                  for (const row of table.querySelectorAll('tbody tr, tr')) {
                    const cells = [...row.querySelectorAll('td, th')];
                    const match = cells.some(c => c.textContent.trim().toLowerCase().replace(/[^a-z0-9]/g, '') === targetClean);
                    if (match) {
                      const startBtn = row.querySelector("button.btn-start, form[action*='/warf/start'] button, button");
                      const form = row.querySelector("form[action*='/warf/start']");
                      if (startBtn) { startBtn.scrollIntoView({ behavior: 'smooth', block: 'center' }); startBtn.click(); return true; }
                      if (form) {
                        form.scrollIntoView({ behavior: 'smooth', block: 'center' });
                        if (typeof form.requestSubmit === 'function') form.requestSubmit(); else form.submit();
                        return true;
                      }
                    }
                  }
                }
                alert('Job ID ' + jobId + ' could not be found in the active portal table.');
                return false;
              };

              const pollCommands = async () => {
                if (!window.pywebview || !window.pywebview.api || typeof window.pywebview.api.get_pending_command !== 'function') return;
                try {
                  const cmd = await window.pywebview.api.get_pending_command();
                  if (cmd && cmd.action === 'start_job' && cmd.job_id) {
                    try {
                      sessionStorage.setItem('nexus_inside_job', '1');
                      localStorage.setItem('nexus_inside_job', '1');
                      sessionStorage.setItem('nexus_active_job_id', cmd.job_id);
                      localStorage.setItem('nexus_active_job_id', cmd.job_id);
                      if (cmd.gatepass) { sessionStorage.setItem('nexus_active_gatepass', cmd.gatepass); localStorage.setItem('nexus_active_gatepass', cmd.gatepass); }
                      if (cmd.client) { sessionStorage.setItem('nexus_active_client', cmd.client); localStorage.setItem('nexus_active_client', cmd.client); }
                    } catch (e) {}
                    executeStartJob(cmd.job_id);
                  } else if (cmd && (cmd.action === 'grab_data_now' || cmd.action === 'force_export')) {
                    lastExportSignature = '';
                    autoExportJobIds(true);
                  } else if (cmd && cmd.action === 'download_job_files') {
                    if (cmd.job_id) window.__nexusJobContext = { job_id: cmd.job_id, gatepass: cmd.gatepass || '', client: cmd.client || '' };
                    downloadAllJobFiles();
                  } else if (cmd && cmd.action === 'set_refresh_interval') {
                    const newSec = Math.max(0, parseInt(cmd.seconds, 10) || 0);
                    refreshInterval = newSec; refreshSeconds = newSec; autoRefreshPaused = newSec <= 0;
                    const btn = document.getElementById('efl-nexus-extract-job-ids');
                    if (btn) btn.textContent = (autoRefreshPaused || refreshInterval <= 0)
                      ? 'Auto-Sync: Off | Export Job IDs'
                      : `Auto-Sync Active (Refresh in ${refreshSeconds}s)`;
                  } else if (cmd && cmd.action === 'go_back') {
                    try {
                      sessionStorage.removeItem('nexus_inside_job');
                      localStorage.removeItem('nexus_inside_job');
                    } catch (e) {}
                    if (window.history.length > 1) window.history.back(); else location.assign(reconUrl);
                  } else if (cmd && cmd.action === 'reload') {
                    location.reload();
                  } else if (cmd && cmd.action === 'go_home') {
                    try {
                      sessionStorage.removeItem('nexus_inside_job');
                      localStorage.removeItem('nexus_inside_job');
                    } catch (e) {}
                    location.assign(cmd.url || reconUrl);
                  }
                } catch (e) {}
              };
              setInterval(pollCommands, 400);

              document.addEventListener('click', (e) => {
                try {
                  const target = e.target && e.target.closest ? e.target.closest('a, button, form') : null;
                  if (!target) return;
                  const href = (target.getAttribute('href') || target.getAttribute('action') || '').toLowerCase();
                  if (href.includes('/warf') || href.includes('/job/') || href.includes('job_id=')) {
                    sessionStorage.setItem('nexus_inside_job', '1');
                    localStorage.setItem('nexus_inside_job', '1');
                  } else if (href.includes('clerk-dashboard') || href.includes('job_type=')) {
                    sessionStorage.removeItem('nexus_inside_job');
                    localStorage.removeItem('nexus_inside_job');
                  }
                } catch (e) {}
              }, true);
            })();
            """;
    }

    public static string BuildPortalAutoLoginScript(string username, string password, string reconciliationUrl)
    {
        if (string.IsNullOrEmpty(username) || string.IsNullOrEmpty(password))
            return "";

        var userVal = JsonSerializer.Serialize(username);
        var passVal = JsonSerializer.Serialize(password);
        var reconVal = JsonSerializer.Serialize(
            string.IsNullOrWhiteSpace(reconciliationUrl) ? GrabberSettingsAndPaths.DefaultReconciliationUrl : reconciliationUrl);

        return $$"""
            (() => {
              const onLoginPage = new URL(location.href).pathname.replace(/\/$/, '') === '/login';
              if (!onLoginPage) {
                if (!sessionStorage.getItem('eflNexusReconciliationOpened')) {
                  sessionStorage.setItem('eflNexusReconciliationOpened', '1');
                  location.assign({{reconVal}});
                }
                return;
              }
              if (sessionStorage.getItem('eflNexusLoginSubmitted')) return;

              let attempts = 0;
              const tryFillAndSubmit = () => {
                attempts++;
                const inputs = [...document.querySelectorAll('input')].filter(input => !input.disabled);
                const password = document.querySelector('#password') || inputs.find(input => (input.type || '').toLowerCase() === 'password');
                const username = document.querySelector('#email') || inputs.find(input => input !== password &&
                  /user|email|login/.test([input.name, input.id, input.autocomplete, input.type].filter(Boolean).join(' ').toLowerCase()))
                  || inputs.find(input => input !== password && ['text', 'email'].includes((input.type || 'text').toLowerCase()));
                if (!username || !password) {
                  if (attempts < 20) setTimeout(tryFillAndSubmit, 200);
                  return;
                }
                const setValue = (input, value) => {
                  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                  setter.call(input, value);
                  input.dispatchEvent(new Event('input', {bubbles: true}));
                  input.dispatchEvent(new Event('change', {bubbles: true}));
                };
                setValue(username, {{userVal}});
                setValue(password, {{passVal}});
                sessionStorage.setItem('eflNexusLoginSubmitted', '1');
                const form = document.querySelector("form[action$='/post-login']") || password.closest('form') || username.closest('form');
                if (form && typeof form.requestSubmit === 'function') form.requestSubmit();
                else if (form) form.submit();
                else password.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', code: 'Enter', bubbles: true}));
              };
              tryFillAndSubmit();
            })();
            """;
    }

    public static string BuildLoadingHistoryAutomationScript(
        string username,
        string password,
        string gatepass,
        bool stopAtGatepass,
        string pageCode = "1992",
        string reportName = "Loading History Report")
    {
        var userVal = JsonSerializer.Serialize(username);
        var passVal = JsonSerializer.Serialize(password);
        var gpVal = JsonSerializer.Serialize(gatepass);
        var stopVal = stopAtGatepass ? "true" : "false";
        var pageCodeVal = JsonSerializer.Serialize(string.IsNullOrWhiteSpace(pageCode) ? "1992" : pageCode.Trim());
        var reportNameVal = JsonSerializer.Serialize(string.IsNullOrWhiteSpace(reportName) ? "Loading History Report" : reportName.Trim());

        return $$"""
            (() => {
              if (window.__eflNexusLoadingHistoryAutomation) return;
              window.__eflNexusLoadingHistoryAutomation = true;
              const log = (message) => console.info('[Loading History] ' + message);
              const setValue = (input, value) => {
                const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                setter.call(input, value);
                input.dispatchEvent(new Event('input', { bubbles: true }));
                input.dispatchEvent(new Event('change', { bubbles: true }));
              };

              let activeGatepass = {{gpVal}};
              const stopAtGatepass = {{stopVal}};
              let targetPageCode = {{pageCodeVal}} || '1992';
              let targetReportName = {{reportNameVal}} || (targetPageCode === '2598' ? 'Inventory by gatepass' : 'Loading History Report');
              let manualStopBypassed = false;

              const resolveGatepass = async () => {
                if (activeGatepass) return activeGatepass;
                if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.get_gatepass === 'function') {
                  try {
                    const res = await window.pywebview.api.get_gatepass();
                    if (res) activeGatepass = String(res).trim();
                  } catch (e) {}
                }
                return activeGatepass;
              };

              const findGatepassInput = () => {
                const searchInDoc = (doc) => {
                  if (!doc || typeof doc.querySelectorAll !== 'function') return null;
                  try {
                    const win = doc.defaultView || (typeof window !== 'undefined' ? window : null);
                    const allInputs = [...doc.querySelectorAll('hj-textbox input, input.k-textbox, input[type="text"], input:not([type])')];
                    const visible = allInputs.filter(input => {
                      if (!input || input.type === 'hidden' || input.disabled || input.readOnly) return false;
                      const tid = input.getAttribute('data-hj-test-id') || (input.parentElement ? input.parentElement.getAttribute('data-hj-test-id') : '') || '';
                      if (tid === 'username' || tid === 'password' || tid === 'menuSearchTextBox') return false;
                      const ph = (input.placeholder || '').toLowerCase();
                      if (ph.includes('user name') || ph.includes('password') || ph.includes('search')) return false;
                      return input.getClientRects ? (input.getClientRects().length > 0) : true;
                    });
                    if (!visible.length) return null;

                    const candidateLabels = [...doc.querySelectorAll('label, span, div, td, th, p, strong, b, hj-field')].filter(el => {
                      if (!el || (el.children && el.children.length > 2)) return false;
                      const txt = (el.textContent || '').trim();
                      return /^(?:Gate\s*Pass(?:\s*ID)?|Gatepass(?:\s*ID)?)$/i.test(txt) ||
                             (/\bgate\s*pass\b/i.test(txt) && !/order\s*number|load\s*id/i.test(txt));
                    });

                    for (const lbl of candidateLabels) {
                      const forAttr = lbl.getAttribute && lbl.getAttribute('for');
                      if (forAttr) {
                        const direct = doc.getElementById(forAttr);
                        if (direct && visible.includes(direct)) return direct;
                        if (direct) {
                          const childInp = direct.querySelector && direct.querySelector('input');
                          if (childInp && visible.includes(childInp)) return childInp;
                        }
                      }
                      let curr = lbl.parentElement;
                      while (curr && curr !== doc.body && curr.tagName !== 'FORM') {
                        const inps = visible.filter(inp => {
                          let p = inp;
                          while (p) { if (p === curr) return true; p = p.parentElement; }
                          return false;
                        });
                        const cText = curr.textContent || '';
                        const hasOthers = /order\s*number|load\s*id/i.test(cText);
                        if (inps.length > 0 && !hasOthers) return inps[0];
                        curr = curr.parentElement;
                      }
                    }

                    for (const inp of visible) {
                      let curr = inp.parentElement;
                      while (curr && curr !== doc.body && curr.tagName !== 'FORM') {
                        const txt = curr.textContent || '';
                        if (/\bgate\s*pass\b/i.test(txt) && !/order\s*number|load\s*id/i.test(txt)) return inp;
                        curr = curr.parentElement;
                      }
                    }

                    if (win && win.ko) {
                      for (const inp of visible) {
                        const parentHj = inp.closest ? inp.closest('hj-textbox') : (inp.parentElement && inp.parentElement.tagName === 'HJ-TEXTBOX' ? inp.parentElement : null);
                        if (parentHj) {
                          try {
                            const ctx = (win.ko.contextFor && win.ko.contextFor(parentHj)) || (win.ko.dataFor && win.ko.dataFor(parentHj));
                            const f = ctx ? (ctx.field || (ctx.$data && ctx.$data.field) || ctx.$data) : null;
                            if (f) {
                              const meta = JSON.stringify({
                                name: typeof f.name === 'function' ? f.name() : f.name,
                                label: typeof f.label === 'function' ? f.label() : f.label,
                                caption: typeof f.caption === 'function' ? f.caption() : f.caption,
                                id: typeof f.id === 'function' ? f.id() : f.id
                              }).toLowerCase();
                              if (meta.includes('gate') && meta.includes('pass')) return inp;
                            }
                          } catch (e) {}
                        }
                      }
                    }

                    for (const inp of visible) {
                      const parentHj = inp.closest ? inp.closest('hj-textbox') : (inp.parentElement && inp.parentElement.tagName === 'HJ-TEXTBOX' ? inp.parentElement : null);
                      const idStr = ((inp.id || '') + ' ' + (inp.name || '') + ' ' + (inp.getAttribute('data-bind') || '')).toLowerCase();
                      const hjStr = parentHj ? ((parentHj.id || '') + ' ' + (parentHj.getAttribute('params') || '') + ' ' + (parentHj.getAttribute('data-hj-test-id') || '')).toLowerCase() : '';
                      if ((idStr.includes('gate') && idStr.includes('pass')) || (hjStr.includes('gate') && hjStr.includes('pass'))) return inp;
                    }

                    if (visible.length === 3) return visible[2];
                    if (doc.activeElement && visible.includes(doc.activeElement)) return doc.activeElement;
                    if (visible.length >= 2) return visible[visible.length - 1];
                    return visible[0] || null;
                  } catch (e) { return null; }
                };

                let target = searchInDoc(document);
                if (target) return target;
                try {
                  for (const iframe of document.querySelectorAll('iframe')) {
                    try {
                      const idoc = iframe.contentDocument || (iframe.contentWindow && iframe.contentWindow.document);
                      if (idoc) { target = searchInDoc(idoc); if (target) return target; }
                    } catch (e) {}
                  }
                } catch (e) {}
                return null;
              };

              const typeGatepassIntoInput = async (input, val) => {
                if (!input || !val) return false;
                try {
                  const win = input.ownerDocument && input.ownerDocument.defaultView ? input.ownerDocument.defaultView : window;
                  if (typeof input.focus === 'function') input.focus();
                  if (typeof input.click === 'function') input.click();
                  if (typeof input.select === 'function') input.select();

                  const proto = win.HTMLInputElement ? win.HTMLInputElement.prototype : HTMLInputElement.prototype;
                  const desc = Object.getOwnPropertyDescriptor(proto, 'value');
                  if (desc && desc.set) desc.set.call(input, ''); else input.value = '';

                  const Ev = win.Event || Event;
                  const KbEv = win.KeyboardEvent || KeyboardEvent || Ev;

                  let current = '';
                  for (let i = 0; i < val.length; i++) {
                    const ch = val[i];
                    current += ch;
                    try { input.dispatchEvent(new KbEv('keydown', { key: ch, bubbles: true, cancelable: true })); } catch (e) {}
                    try { input.dispatchEvent(new KbEv('keypress', { key: ch, bubbles: true, cancelable: true })); } catch (e) {}
                    if (desc && desc.set) desc.set.call(input, current); else input.value = current;
                    try { input.dispatchEvent(new (win.InputEvent || Ev)('input', { bubbles: true, data: ch, inputType: 'insertText' })); }
                    catch (e) { input.dispatchEvent(new Ev('input', { bubbles: true })); }
                    try { input.dispatchEvent(new KbEv('keyup', { key: ch, bubbles: true, cancelable: true })); } catch (e) {}
                    if (win.ko && typeof win.ko.dataFor === 'function') {
                      try {
                        const inner = win.ko.dataFor(input);
                        if (inner && typeof inner._value === 'function') {
                          inner._value(current);
                          if (typeof inner._value.valueHasMutated === 'function') inner._value.valueHasMutated();
                        }
                      } catch (e) {}
                    }
                    await new Promise(r => setTimeout(r, 20));
                  }

                  if (desc && desc.set) desc.set.call(input, val); else input.value = val;
                  if (win.ko) {
                    try {
                      if (typeof win.ko.dataFor === 'function') {
                        const inner = win.ko.dataFor(input);
                        if (inner && typeof inner._value === 'function') {
                          inner._value(val);
                          if (typeof inner._value.valueHasMutated === 'function') inner._value.valueHasMutated();
                        }
                      }
                      const hjParent = input.closest ? input.closest('hj-textbox') : (input.parentElement && input.parentElement.tagName === 'HJ-TEXTBOX' ? input.parentElement : null);
                      if (hjParent) {
                        const parentCtx = (win.ko.contextFor && win.ko.contextFor(hjParent)) || (win.ko.dataFor && win.ko.dataFor(hjParent));
                        if (parentCtx) {
                          const f = parentCtx.field || (parentCtx.$data && parentCtx.$data.field);
                          if (f && typeof f.value === 'function') {
                            f.value(val);
                            if (typeof f.value.valueHasMutated === 'function') f.value.valueHasMutated();
                          } else if (parentCtx.value && typeof parentCtx.value === 'function') {
                            parentCtx.value(val);
                            if (typeof parentCtx.value.valueHasMutated === 'function') parentCtx.value.valueHasMutated();
                          }
                        }
                      }
                    } catch (e) {}
                  }

                  input.dispatchEvent(new Ev('input', { bubbles: true }));
                  input.dispatchEvent(new Ev('change', { bubbles: true }));
                  try { input.dispatchEvent(new FocusEvent('blur', { bubbles: true })); }
                  catch (e) { input.dispatchEvent(new Ev('blur', { bubbles: true })); }
                  if (typeof input.blur === 'function') input.blur();
                  input.setAttribute('data-efl-nexus-gatepass-typed', val);
                  return true;
                } catch (e) { return false; }
              };

              const findQueryButton = () => {
                const searchInDoc = (doc) => {
                  if (!doc || typeof doc.querySelectorAll !== 'function') return null;
                  try {
                    const svgIcon = doc.querySelector("*[style*='query.svg' i], div[style*='query.svg' i], img[src*='query.svg' i], [data-bind*='sourceStyle'][style*='query' i]");
                    const svgSource = svgIcon ? ((svgIcon.getAttribute('style') || '') + ' ' + (svgIcon.getAttribute('src') || '')).toLowerCase() : '';
                    if (svgIcon && svgSource.includes('query')) {
                      const btn = svgIcon.closest ? svgIcon.closest('a, button, [role="button"], hj-button') : null;
                      return btn || svgIcon;
                    }
                    for (const sp of doc.querySelectorAll("span[data-bind*='observableText'], *[data-bind*='observableText']")) {
                      if (/^Query$/i.test((sp.textContent || '').trim())) {
                        const btn = sp.closest ? sp.closest('a, button, [role="button"], hj-button') : null;
                        return btn || sp;
                      }
                    }
                    for (const a of doc.querySelectorAll("a[data-bind*='click: click'], button[data-bind*='click: click'], a[data-bind*='click'], [data-bind*='click: click']")) {
                      const txt = (a.textContent || '').trim();
                      if (/^Query$/i.test(txt) || (a.innerHTML && /query\.svg/i.test(a.innerHTML))) return a;
                    }
                    const win = doc.defaultView || (typeof window !== 'undefined' ? window : null);
                    if (win && win.ko && typeof win.ko.dataFor === 'function') {
                      for (const el of doc.querySelectorAll('a, button, [role="button"], hj-button')) {
                        try {
                          const data = win.ko.dataFor(el);
                          if (data) {
                            const text = typeof data.observableText === 'function' ? data.observableText() : data.observableText;
                            const src = typeof data.sourceStyle === 'function' ? JSON.stringify(data.sourceStyle()) : JSON.stringify(data.sourceStyle || '');
                            if (String(text).trim().toLowerCase() === 'query' || (src && src.toLowerCase().includes('query.svg'))) return el;
                          }
                        } catch (e) {}
                      }
                    }
                    const byTestId = doc.querySelector("[data-hj-test-id*='query' i], [data-hj-test-id*='Query']");
                    if (byTestId) return byTestId;
                    const clickable = [...doc.querySelectorAll('button, a, hj-button, [role="button"], span, div')];
                    const match = clickable.find(el => {
                      const txt = (el.textContent || '').trim();
                      if (/^(?:Query|Run Query)$/i.test(txt)) return true;
                      return /^Query$/i.test((el.getAttribute('title') || '').trim()) || /^Query$/i.test((el.getAttribute('aria-label') || '').trim());
                    });
                    if (match) return (match.closest && match.closest('button, a, [role="button"], hj-button')) || match;
                    const toolbarItem = clickable.find(el => {
                      const txt = (el.textContent || '').trim();
                      const words = txt.split(/\s+/);
                      return words.some(w => /^query$/i.test(w)) && !words.some(w => /^reset$/i.test(w)) && txt.length <= 25;
                    });
                    if (toolbarItem) return (toolbarItem.closest && toolbarItem.closest('button, a, [role="button"], hj-button')) || toolbarItem;
                    return null;
                  } catch (e) { return null; }
                };
                const searchAllDocs = (rootDoc) => {
                  if (!rootDoc) return null;
                  const res = searchInDoc(rootDoc); if (res) return res;
                  try {
                    for (const frame of rootDoc.querySelectorAll('iframe, frame')) {
                      try {
                        const cdoc = frame.contentDocument || (frame.contentWindow && frame.contentWindow.document);
                        if (cdoc) { const nested = searchAllDocs(cdoc); if (nested) return nested; }
                      } catch (e) {}
                    }
                  } catch (e) {}
                  return null;
                };
                let target = searchAllDocs(document);
                if (target) return target;
                try {
                  if (window.frames && window.frames.length > 0) {
                    for (let i = 0; i < window.frames.length; i++) {
                      try { if (window.frames[i].document) { target = searchAllDocs(window.frames[i].document); if (target) return target; } } catch (e) {}
                    }
                  }
                } catch (e) {}
                return null;
              };

              const clickQueryButton = (btn) => {
                if (!btn) return false;
                try {
                  const doc = btn.ownerDocument || document;
                  const win = (doc && doc.defaultView) || (typeof window !== 'undefined' ? window : null);
                  if (typeof btn.focus === 'function') try { btn.focus(); } catch (e) {}
                  const span = btn.querySelector ? btn.querySelector("span[data-bind*='observableText'], span") : null;
                  const icon = btn.querySelector ? btn.querySelector("*[style*='query.svg' i], [data-bind*='sourceStyle']") : null;
                  const ko = (win && win.ko) || (typeof window !== 'undefined' && window.ko);
                  const vm = (ko && typeof ko.dataFor === 'function') ? (ko.dataFor(btn) || (span ? ko.dataFor(span) : null) || (icon ? ko.dataFor(icon) : null)) : null;
                  let vmRan = false;
                  if (vm && typeof vm.click === 'function') {
                    const origClick = vm.click;
                    vm.click = function(...args) { vmRan = true; return origClick.apply(this, args); };
                  }
                  if (typeof btn.click === 'function') btn.click(); else return false;
                  if (vm && typeof vm.click === 'function' && !vmRan) {
                    const fakeEvt = (win && win.MouseEvent) ? new win.MouseEvent('click', { bubbles: true, cancelable: true, view: win }) : { type: 'click' };
                    vm.click.call(vm, vm, fakeEvt);
                  }
                  return true;
                } catch (e) { return false; }
              };

              const findExportButton = () => {
                const searchInDoc = (doc) => {
                  if (!doc || typeof doc.querySelectorAll !== 'function') return null;
                  try {
                    const icon = doc.querySelector("i.fa-share-square-o, i[class*='fa-share-square'], i[class*='share-square']");
                    if (icon) return (icon.closest && icon.closest('a, button, [role="button"], hj-button')) || icon;
                    for (const sp of doc.querySelectorAll("span[data-bind*='observableText'], *[data-bind*='observableText']")) {
                      if (/^Export$/i.test((sp.textContent || '').trim())) return (sp.closest && sp.closest('a, button, [role="button"], hj-button')) || sp;
                    }
                    for (const a of doc.querySelectorAll("a[data-bind*='click: click'], button[data-bind*='click: click'], a[data-bind*='click'], [data-bind*='click: click']")) {
                      const txt = (a.textContent || '').trim();
                      if (/^Export$/i.test(txt) || (a.innerHTML && /fa-share-square/i.test(a.innerHTML))) return a;
                    }
                    const win = doc.defaultView || (typeof window !== 'undefined' ? window : null);
                    if (win && win.ko && typeof win.ko.dataFor === 'function') {
                      for (const el of doc.querySelectorAll('a, button, [role="button"], hj-button')) {
                        try {
                          const data = win.ko.dataFor(el);
                          if (data) {
                            const text = typeof data.observableText === 'function' ? data.observableText() : data.observableText;
                            if (String(text).trim().toLowerCase() === 'export') return el;
                          }
                        } catch (e) {}
                      }
                    }
                    const byTestId = doc.querySelector("[data-hj-test-id*='export' i], [data-hj-test-id*='Export']");
                    if (byTestId) return byTestId;
                    const clickable = [...doc.querySelectorAll('button, a, hj-button, [role="button"], span, div')];
                    const match = clickable.find(el => {
                      const txt = (el.textContent || '').trim();
                      if (/^(?:Export|Export Report)$/i.test(txt)) return true;
                      return /^Export$/i.test((el.getAttribute('title') || '').trim()) || /^Export$/i.test((el.getAttribute('aria-label') || '').trim());
                    });
                    if (match) return (match.closest && match.closest('button, a, [role="button"], hj-button')) || match;
                    return null;
                  } catch (e) { return null; }
                };
                const searchAllDocs = (rootDoc) => {
                  if (!rootDoc) return null;
                  const res = searchInDoc(rootDoc); if (res) return res;
                  try {
                    for (const frame of rootDoc.querySelectorAll('iframe, frame')) {
                      try {
                        const cdoc = frame.contentDocument || (frame.contentWindow && frame.contentWindow.document);
                        if (cdoc) { const nested = searchAllDocs(cdoc); if (nested) return nested; }
                      } catch (e) {}
                    }
                  } catch (e) {}
                  return null;
                };
                let target = searchAllDocs(document);
                if (target) return target;
                try {
                  if (window.frames && window.frames.length > 0) {
                    for (let i = 0; i < window.frames.length; i++) {
                      try { if (window.frames[i].document) { target = searchAllDocs(window.frames[i].document); if (target) return target; } } catch (e) {}
                    }
                  }
                } catch (e) {}
                return null;
              };

              let exportSubmitted = false;
              const clickExportButton = (btn) => {
                if (!btn || exportSubmitted) return false;
                try {
                  exportSubmitted = true;
                  if (typeof sessionStorage !== 'undefined' && sessionStorage.setItem) sessionStorage.setItem('eflNexusLoadingHistoryExportSubmitted', '1');
                  const doc = btn.ownerDocument || document;
                  const win = (doc && doc.defaultView) || (typeof window !== 'undefined' ? window : null);
                  if (typeof btn.focus === 'function') try { btn.focus(); } catch (e) {}
                  const ko = (win && win.ko) || (typeof window !== 'undefined' && window.ko);
                  const vm = (ko && typeof ko.dataFor === 'function')
                    ? (ko.dataFor(btn) || (btn.querySelector ? ko.dataFor(btn.querySelector('span')) : null) || (btn.querySelector ? ko.dataFor(btn.querySelector('i')) : null))
                    : null;
                  let vmRan = false;
                  if (vm && typeof vm.click === 'function') {
                    const origClick = vm.click;
                    vm.click = function(...args) { vmRan = true; return origClick.apply(this, args); };
                  }
                  if (typeof btn.click === 'function') btn.click();
                  if (vm && typeof vm.click === 'function' && !vmRan) {
                    const fakeEvt = (win && win.MouseEvent) ? new win.MouseEvent('click', { bubbles: true, cancelable: true, view: win }) : { type: 'click' };
                    vm.click.call(vm, vm, fakeEvt);
                  }
                  return true;
                } catch (e) { return false; }
              };

              let attempts = 0;
              let lastMenuClick = 0;
              let searchEntered = false;
              let isTyping = false;
              let queryClickCount = 0;
              let lastQueryClickTime = 0;
              let exportClickCount = 0;

              const automate = async () => {
                attempts++;
                try {
                  const checkTexts = [(document.body && document.body.textContent) || ''];
                  for (const f of document.querySelectorAll('iframe')) {
                    try { const fdoc = f.contentDocument || (f.contentWindow && f.contentWindow.document); if (fdoc && fdoc.body) checkTexts.push(fdoc.body.textContent || ''); } catch (e) {}
                  }
                  for (const txt of checkTexts) {
                    if (txt.includes("Server Error in '/SupplyChainAdvantage'") || (txt.includes('Export [') && txt.includes('was not found'))) {
                      if (typeof sessionStorage !== 'undefined' && sessionStorage.removeItem) {
                        sessionStorage.setItem('eflNexusLoadingHistoryRecoveryNeeded', '1');
                        sessionStorage.removeItem('eflNexusLoadingHistoryQuerySubmitted');
                        sessionStorage.removeItem('eflNexusLoadingHistoryExportSubmitted');
                      }
                      exportSubmitted = false; exportClickCount = 0; queryClickCount = 0; lastQueryClickTime = 0;
                      if (window.history && typeof window.history.back === 'function' && window.history.length > 1) window.history.back();
                      else window.location.reload();
                      return;
                    }
                  }
                } catch (e) {}

                if (sessionStorage.getItem('eflNexusLoadingHistoryRecoveryNeeded') === '1') {
                  sessionStorage.removeItem('eflNexusLoadingHistoryRecoveryNeeded');
                  sessionStorage.removeItem('eflNexusLoadingHistoryQuerySubmitted');
                  sessionStorage.removeItem('eflNexusLoadingHistoryExportSubmitted');
                  queryClickCount = 0; lastQueryClickTime = 0; exportClickCount = 0; exportSubmitted = false;
                }

                const username = document.querySelector("hj-textbox[data-hj-test-id='username'] input, input.k-textbox[placeholder='User Name']");
                const password = document.querySelector("hj-password-textbox[data-hj-test-id='password'] input, input[type='password']");
                if (username && password && username.getClientRects().length > 0 && password.getClientRects().length > 0) {
                  const loginButton = document.querySelector("hj-button[data-hj-test-id='actionButton'] button")
                    || [...document.querySelectorAll('hj-button button, button')].find(button => button.textContent.trim() === 'Login');
                  if (loginButton && !sessionStorage.getItem('eflNexusKorberLoginSubmitted')) {
                    setValue(username, {{userVal}});
                    setValue(password, {{passVal}});
                    loginButton.click();
                    sessionStorage.setItem('eflNexusKorberLoginSubmitted', '1');
                  }
                  if (attempts < 240) setTimeout(automate, 250);
                  return;
                }

                const menuToggle = document.querySelector("a#menuButtonToggle[data-hj-test-id='menuButtonToggle']");
                if (menuToggle && !sessionStorage.getItem('eflNexusLoadingHistoryReportOpened')) {
                  const menuIsOpen = menuToggle.classList.contains('active') || menuToggle.getAttribute('aria-expanded') === 'true';
                  if (!menuIsOpen && Date.now() - lastMenuClick > 1000) { menuToggle.click(); lastMenuClick = Date.now(); }
                  const searchBox = document.querySelector("input[data-hj-test-id='menuSearchTextBox']");
                  if (searchBox && searchBox.getClientRects().length > 0) {
                    if (!searchEntered || searchBox.value !== targetPageCode) {
                      setValue(searchBox, targetPageCode);
                      searchBox.dispatchEvent(new Event('keyup', { bubbles: true }));
                      searchBox.focus();
                      searchEntered = true;
                    }
                    const matchReportTitle = (text) => {
                      const t = String(text || '').trim().toLowerCase();
                      const target = String(targetReportName || '').trim().toLowerCase();
                      if (target && t === target) return true;
                      if (targetPageCode === '2598') {
                        return t.includes('inventory') && (t.includes('gatepass') || t.includes('gate pass'));
                      }
                      return t.includes('loading history');
                    };
                    const title = [...document.querySelectorAll('a span.title, a .title, a')].find(el => {
                      if (!el || (el.children && el.children.length > 2)) return false;
                      return matchReportTitle(el.textContent) && (el.getClientRects ? el.getClientRects().length > 0 : true);
                    });
                    const reportLink = title && (title.tagName === 'A' ? title : title.closest('a'));
                    if (reportLink && reportLink.getClientRects().length > 0) {
                      if (typeof sessionStorage.removeItem === 'function') {
                        sessionStorage.removeItem('eflNexusLoadingHistoryQuerySubmitted');
                        sessionStorage.removeItem('eflNexusLoadingHistoryExportSubmitted');
                        sessionStorage.removeItem('eflNexusLoadingHistoryRecoveryNeeded');
                        sessionStorage.removeItem('eflNexusLoadingHistoryStoppedAtGatepass');
                      }
                      reportLink.click();
                      sessionStorage.setItem('eflNexusLoadingHistoryReportOpened', '1');
                      setTimeout(automate, 250);
                      return;
                    }
                  }
                  if (attempts < 240) setTimeout(automate, 250);
                  return;
                }

                if (stopAtGatepass && typeof sessionStorage !== 'undefined' && sessionStorage.getItem('eflNexusLoadingHistoryStoppedAtGatepass') === '1') {
                  if (!manualStopBypassed) return;
                }

                const hasSubmittedQuery = queryClickCount > 0 || sessionStorage.getItem('eflNexusLoadingHistoryQuerySubmitted') === '1';

                if (!hasSubmittedQuery) {
                  const gpInput = findGatepassInput();
                  if (stopAtGatepass && gpInput && !manualStopBypassed) {
                    try {
                      if (typeof gpInput.focus === 'function') gpInput.focus();
                      if (typeof gpInput.scrollIntoView === 'function') gpInput.scrollIntoView({ block: 'center', inline: 'center' });
                    } catch (e) {}
                    sessionStorage.setItem('eflNexusLoadingHistoryStoppedAtGatepass', '1');
                    return;
                  }
                  if (gpInput && !isTyping) {
                    let gp = activeGatepass;
                    if (!gp) gp = await resolveGatepass();
                    if (gp && gpInput.value !== gp && gpInput.getAttribute('data-efl-nexus-gatepass-typed') !== gp) {
                      isTyping = true;
                      try {
                        queryClickCount = 0; lastQueryClickTime = 0; exportClickCount = 0; exportSubmitted = false;
                        if (typeof sessionStorage.removeItem === 'function') {
                          sessionStorage.removeItem('eflNexusLoadingHistoryQuerySubmitted');
                          sessionStorage.removeItem('eflNexusLoadingHistoryExportSubmitted');
                        }
                        await typeGatepassIntoInput(gpInput, gp);
                      } finally { isTyping = false; }
                    }
                  }

                  const currentVal = (gpInput && gpInput.value ? gpInput.value.trim() : '') || (gpInput ? (gpInput.getAttribute('data-efl-nexus-gatepass-typed') || '') : '');
                  const isReadyToQuery = activeGatepass ? currentVal === activeGatepass : currentVal.length > 0;
                  if (isReadyToQuery && !isTyping) {
                    const now = Date.now();
                    if (queryClickCount < 3 && (now - lastQueryClickTime > 2000)) {
                      const queryBtn = findQueryButton();
                      if (queryBtn && clickQueryButton(queryBtn)) {
                        queryClickCount++; lastQueryClickTime = now;
                        sessionStorage.setItem('eflNexusLoadingHistoryQuerySubmitted', '1');
                        if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.report_gatepass === 'function') {
                          try { window.pywebview.api.report_gatepass(currentVal); } catch (e) {}
                        }
                      }
                    }
                  }
                }

                const hasExported = exportClickCount > 0 || exportSubmitted || sessionStorage.getItem('eflNexusLoadingHistoryExportSubmitted') === '1';
                if (hasSubmittedQuery && !hasExported) {
                  const now = Date.now();
                  const timeSinceQuery = lastQueryClickTime > 0 ? (now - lastQueryClickTime) : 2500;
                  if (timeSinceQuery >= 2500) {
                    const exportBtn = findExportButton();
                    if (exportBtn) {
                      const isDisabled = (exportBtn.classList && (exportBtn.classList.contains('k-state-disabled') || exportBtn.classList.contains('disabled')))
                        || exportBtn.getAttribute('aria-disabled') === 'true' || exportBtn.getAttribute('disabled') !== null;
                      let isMaskVisible = false;
                      try {
                        const btnDoc = exportBtn.ownerDocument || document;
                        const mask = btnDoc.querySelector('.k-loading-mask, .k-loading-image, .k-i-loading') || document.querySelector('.k-loading-mask, .k-loading-image, .k-i-loading');
                        if (mask && (mask.offsetParent !== null || (mask.getClientRects && mask.getClientRects().length > 0))) isMaskVisible = true;
                      } catch (e) {}
                      if (!isDisabled && !isMaskVisible && clickExportButton(exportBtn)) {
                        exportClickCount = 1;
                      }
                    }
                  }
                }

                if (attempts < 240) setTimeout(automate, 250);
              };
              automate();

              const pollLoadingHistoryCommands = async () => {
                if (!window.pywebview || !window.pywebview.api || typeof window.pywebview.api.get_pending_command !== 'function') return;
                try {
                  const cmd = await window.pywebview.api.get_pending_command();
                  if (cmd && (cmd.gatepass || cmd.action === 'query_and_export' || cmd.action === 'download_loading_history' || cmd.page_code)) {
                    if (cmd.gatepass) activeGatepass = String(cmd.gatepass || '').trim();
                    if (cmd.page_code && String(cmd.page_code).trim() !== targetPageCode) {
                      targetPageCode = String(cmd.page_code).trim();
                      if (cmd.report_name) targetReportName = String(cmd.report_name).trim();
                      else if (targetPageCode === '2598') targetReportName = 'Inventory by gatepass';
                      else targetReportName = 'Loading History Report';
                      searchEntered = false;
                      try {
                        sessionStorage.removeItem('eflNexusLoadingHistoryReportOpened');
                      } catch (e) {}
                    }
                    manualStopBypassed = true;
                    try {
                      sessionStorage.removeItem('eflNexusLoadingHistoryStoppedAtGatepass');
                      sessionStorage.removeItem('eflNexusLoadingHistoryQuerySubmitted');
                      sessionStorage.removeItem('eflNexusLoadingHistoryExportSubmitted');
                    } catch (e) {}
                    queryClickCount = 0; lastQueryClickTime = 0; exportClickCount = 0; exportSubmitted = false; attempts = 0;
                    automate();
                  }
                } catch (e) {}
              };
              if (typeof setInterval === 'function') setInterval(pollLoadingHistoryCommands, 500);
            })();
            """;
    }
}
