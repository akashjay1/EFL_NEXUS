
            (() => {
              const reconUrl = "https://active.efl3plofc.com/clerk-dashboard";
              const isReconciliationPage = () => {
                try {
                  const path = (location.pathname || '').toLowerCase();
                  const href = (location.href || '').toLowerCase();
                  if (path.includes('login') || path.includes('/warf/start')) return false;
                  if (path.includes('clerk-dashboard') || href.includes('clerk-dashboard') || href.includes('job_type=outbound')) return true;
                  const allTables = [...document.querySelectorAll('table')];
                  return allTables.some(t => {
                    const txt = (t.textContent || '').toLowerCase().replace(/[^a-z0-9]/g, '');
                    return txt.includes('jobid') || txt.includes('jobnumber') || txt.includes('jobno');
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
                  const jIdx = headers.findIndex(h => ['jobid', 'jobnumber', 'jobno', 'job', 'job#'].includes(h) || h.includes('jobid'));
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
                  if (clientColIndex >= 0 && clientColIndex < cells.length && cells[clientColIndex]) {
                    clientVal = cells[clientColIndex].textContent.trim();
                  }
                  let stVal = '';
                  if (statusColIndex >= 0 && statusColIndex < cells.length && cells[statusColIndex]) {
                    stVal = cells[statusColIndex].textContent.trim();
                  }
                  let whVal = '';
                  if (whColIndex >= 0 && whColIndex < cells.length && cells[whColIndex]) {
                    whVal = cells[whColIndex].textContent.trim();
                  }
                  let gatepassVal = '';
                  if (gatepassColIndex >= 0 && gatepassColIndex < cells.length && cells[gatepassColIndex]) {
                    gatepassVal = cells[gatepassColIndex].textContent.trim();
                  }
                  let sealVal = '';
                  if (sealColIndex >= 0 && sealColIndex < cells.length && cells[sealColIndex]) {
                    sealVal = cells[sealColIndex].textContent.trim();
                  }
                  let deliveryVal = '';
                  if (deliveryColIndex >= 0 && deliveryColIndex < cells.length && cells[deliveryColIndex]) {
                    deliveryVal = cells[deliveryColIndex].textContent.trim();
                  }
                  values.push({
                    job_id: jobVal,
                    client: clientVal,
                    status: stVal,
                    warehouse: whVal,
                    gatepass: gatepassVal,
                    seal: sealVal,
                    delivery_location: deliveryVal
                  });
                }
                return values;
              };

              let lastExportSignature = '';
              let isExporting = false;

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

              let refreshInterval = 10;
              let refreshSeconds = refreshInterval;
              let autoRefreshPaused = refreshInterval <= 0;

              const attachButton = () => {
                if (document.getElementById('efl-nexus-extract-job-ids')) return;
                const button = document.createElement('button');
                button.id = 'efl-nexus-extract-job-ids';
                button.type = 'button';
                button.textContent = (refreshInterval > 0) ? `Auto-Sync: ${refreshInterval}s | Export Job IDs` : 'Auto-Sync: Off | Export Job IDs';
                Object.assign(button.style, {
                  position: 'fixed', right: '22px', bottom: '22px', zIndex: 2147483647,
                  border: '0', borderRadius: '6px', padding: '11px 16px', cursor: 'pointer',
                  background: '#0d1b2a', color: '#ffffff', fontWeight: '700', boxShadow: '0 3px 12px #0005',
                  transition: 'background 0.2s, transform 0.1s'
                });
                button.addEventListener('click', () => autoExportJobIds(true));
                if (document.body) document.body.appendChild(button);
              };
              attachButton();
              setInterval(attachButton, 1000);

              // Auto-export periodically while on reconciliation page
              const pollAutoExport = () => {
                if (isReconciliationPage()) {
                  autoExportJobIds(false);
                }
              };
              setInterval(pollAutoExport, 1500);
              setTimeout(pollAutoExport, 500);
              setTimeout(pollAutoExport, 1000);

              // Auto-Refresh timer when in reconciliation page
              const tickCountdown = () => {
                if (!isReconciliationPage() || autoRefreshPaused || refreshInterval <= 0) {
                  refreshSeconds = refreshInterval;
                  const btn = document.getElementById('efl-nexus-extract-job-ids');
                  if (btn) {
                    if (!isReconciliationPage()) {
                      btn.style.display = 'none';
                    } else {
                      btn.style.display = 'block';
                      btn.textContent = 'Auto-Sync: Off | Export Job IDs';
                    }
                  }
                  return;
                }
                const btn = document.getElementById('efl-nexus-extract-job-ids');
                if (btn) {
                  btn.style.display = 'block';
                }
                refreshSeconds--;
                if (btn && refreshSeconds > 0) {
                  btn.textContent = `Auto-Sync Active (Refresh in ${refreshSeconds}s)`;
                }
                if (refreshSeconds <= 0) {
                  refreshSeconds = refreshInterval;
                  if (btn) btn.textContent = 'Refreshing...';
                  autoExportJobIds(false).finally(() => {
                    if (isReconciliationPage() && !autoRefreshPaused && refreshInterval > 0) {
                      location.reload();
                    }
                  });
                }
              };
              setInterval(tickCountdown, 1000);

              // Floating Go Back button in web page
              const attachBackButton = () => {
                if (document.getElementById('efl-nexus-go-back')) return;
                const backBtn = document.createElement('button');
                backBtn.id = 'efl-nexus-go-back';
                backBtn.type = 'button';
                backBtn.textContent = '◀ Go Back';
                Object.assign(backBtn.style, {
                  position: 'fixed', left: '22px', bottom: '22px', zIndex: 2147483647,
                  border: '0', borderRadius: '6px', padding: '11px 16px', cursor: 'pointer',
                  background: '#0d1b2a', color: '#ffffff', fontWeight: '700', boxShadow: '0 3px 12px #0005'
                });
                backBtn.addEventListener('click', () => {
                  if (window.history.length > 1) {
                    window.history.back();
                  } else {
                    location.assign(reconUrl);
                  }
                });
                if (document.body) document.body.appendChild(backBtn);
              };
              attachBackButton();
              setInterval(attachBackButton, 1000);

              // Intercept manual clicks on download buttons and guarantee they save to Downloads
              document.addEventListener('click', async (event) => {
                try {
                  const link = event.target ? event.target.closest('a') : null;
                  if (!link) return;
                  const href = (link.href || '').trim();
                  if (!href || href.startsWith('javascript:') || href.endsWith('#')) return;

                  const hasDownloadAttr = link.hasAttribute('download');
                  const isDownloadClass = link.classList.contains('btn-download') || link.classList.contains('download');
                  const isFileExt = /\\.(xlsx|xls|pdf|csv|docx|doc|zip|rar|png|jpg|jpeg|txt)$/i.test(href.split('?')[0]);
                  const isUploadPath = href.includes('/uploads/') || href.includes('/storage/');

                  if (!hasDownloadAttr && !isDownloadClass && !isFileExt && !isUploadPath) {
                    return;
                  }

                  event.preventDefault();
                  event.stopPropagation();

                  const originalText = link.textContent;
                  const filename = (link.getAttribute('download') || link.textContent || '').trim() || href.split('/').pop().split('?')[0];

                  link.textContent = '⏳ Downloading...';
                  link.style.pointerEvents = 'none';

                  let b64 = '';
                  try {
                    const resp = await fetch(href, { credentials: 'include' });
                    if (resp.ok) {
                      const blob = await resp.blob();
                      const reader = new FileReader();
                      b64 = await new Promise((resolve) => {
                        reader.onloadend = () => resolve((reader.result || '').split(',')[1] || '');
                        reader.readAsDataURL(blob);
                      });
                    }
                  } catch (fetchErr) {
                    console.warn('[NEXUS] In-page fetch error:', fetchErr);
                  }

                  if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.download_file === 'function') {
                    const res = await window.pywebview.api.download_file({
                      filename: filename,
                      base64: b64,
                      url: href
                    });
                    if (res && res.success) {
                      link.textContent = '✓ Saved to Downloads!';
                      link.style.backgroundColor = '#10b981';
                      link.style.color = '#ffffff';
                      setTimeout(() => {
                        link.textContent = originalText;
                        link.style.backgroundColor = '';
                        link.style.color = '';
                        link.style.pointerEvents = '';
                      }, 3000);
                    } else {
                      link.textContent = '❌ Download failed';
                      link.style.backgroundColor = '#ef4444';
                      setTimeout(() => {
                        link.textContent = originalText;
                        link.style.backgroundColor = '';
                        link.style.color = '';
                        link.style.pointerEvents = '';
                      }, 3000);
                    }
                  } else {
                    link.textContent = originalText;
                    link.style.pointerEvents = '';
                  }
                } catch (err) {
                  console.error('[NEXUS] Click download handler error:', err);
                }
              }, true);

              // Command listener: executes "Start" action for a selected job in the web portal
              const executeStartJob = (jobId) => {
                const targetClean = String(jobId || '').trim().toLowerCase().replace(/[^a-z0-9]/g, '');
                if (!targetClean) return;
                const tables = [...document.querySelectorAll('table')];
                for (const table of tables) {
                  const rows = [...table.querySelectorAll('tbody tr, tr')];
                  for (const row of rows) {
                    const cells = [...row.querySelectorAll('td, th')];
                    const match = cells.some(c => {
                      const txt = c.textContent.trim().toLowerCase().replace(/[^a-z0-9]/g, '');
                      return txt === targetClean;
                    });
                    if (match) {
                      const startBtn = row.querySelector("button.btn-start, form[action*='/warf/start'] button, button");
                      const form = row.querySelector("form[action*='/warf/start']");
                      if (startBtn) {
                        startBtn.scrollIntoView({ behavior: 'smooth', block: 'center' });
                        startBtn.click();
                        return true;
                      } else if (form) {
                        form.scrollIntoView({ behavior: 'smooth', block: 'center' });
                        if (typeof form.requestSubmit === 'function') {
                          form.requestSubmit();
                        } else {
                          form.submit();
                        }
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
                    executeStartJob(cmd.job_id);
                  } else if (cmd && cmd.action === 'set_refresh_interval') {
                    const newSec = Math.max(0, parseInt(cmd.seconds, 10) || 0);
                    refreshInterval = newSec;
                    refreshSeconds = newSec;
                    autoRefreshPaused = newSec <= 0;
                    const btn = document.getElementById('efl-nexus-extract-job-ids');
                    if (btn) {
                      if (autoRefreshPaused || refreshInterval <= 0) {
                        btn.textContent = 'Auto-Sync: Off | Export Job IDs';
                      } else {
                        btn.textContent = `Auto-Sync Active (Refresh in ${refreshSeconds}s)`;
                      }
                    }
                  } else if (cmd && cmd.action === 'go_back') {
                    if (window.history.length > 1) {
                      window.history.back();
                    } else {
                      location.assign(reconUrl);
                    }
                  } else if (cmd && cmd.action === 'reload') {
                    location.reload();
                  } else if (cmd && cmd.action === 'go_home') {
                    location.assign(cmd.url || reconUrl);
                  }
                } catch (e) {}
              };
              setInterval(pollCommands, 400);
            })();
        