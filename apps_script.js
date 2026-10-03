/**
 * VGK EDGE SIM - Google Sheets Apps Script
 *
 * Instructions:
 * 1. Open your Google Sheet.
 * 2. Click Extensions -> Apps Script.
 * 3. Delete any code there, paste this entire file, and click Save (the disk icon).
 * 4. Refresh your Google Sheet. You will see VGK EDGE and MY BETS menus at the top.
 * 5. On first run, click VGK EDGE -> Setup Wager Tracker to wire up dropdowns and Kelly controls.
 */

const GITHUB_OWNER   = 'BradR98';
const GITHUB_REPO    = 'vgk-edge-sim';
const SIM_WORKFLOW   = 'Auto_2_Sim.yml';
const GRADE_WORKFLOW = 'Auto_3_PostGame.yml';
const GITHUB_PAT     = PropertiesService.getScriptProperties().getProperty('NHL Team X Team Edge');

// ---------------------------------------------------------------------------
// Menus
// ---------------------------------------------------------------------------
function onOpen() {
  const ui = SpreadsheetApp.getUi();

  ui.createMenu('VGK EDGE')
    .addItem('Run Manual Update',   'triggerSim')
    .addItem('Grade Wagers',        'triggerGradeWagers')
    .addItem('Update Wager Search', 'updateWagerSearch')
    .addSeparator()
    .addItem('Setup Wager Tracker', 'setupWagerTracker')
    .addToUi();

  ui.createMenu('MY BETS')
    .addItem('Print Open Wagers', 'printOpenWagers')
    .addToUi();
}

// ---------------------------------------------------------------------------
// GitHub Action Triggers
// ---------------------------------------------------------------------------
function triggerSim() {
  _triggerWorkflow(SIM_WORKFLOW, 'Monte Carlo Simulation triggered! Give it ~45 seconds to run.');
}

function triggerGradeWagers() {
  _triggerWorkflow(GRADE_WORKFLOW, 'Post-game audit triggered! Give it ~60 seconds to grade your wagers.');
}

function _triggerWorkflow(workflowId, successMsg) {
  const ui = SpreadsheetApp.getUi();
  if (!GITHUB_PAT) {
    ui.alert('Configuration Error',
      "GitHub Token not found. Add it to Project Settings → Script Properties with key 'NHL Team X Team Edge'.",
      ui.ButtonSet.OK);
    return;
  }
  const url = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/actions/workflows/${workflowId}/dispatches`;
  const options = {
    method: 'post',
    headers: { Authorization: `Bearer ${GITHUB_PAT}`, Accept: 'application/vnd.github.v3+json' },
    payload: JSON.stringify({ ref: 'master' }),
    muteHttpExceptions: true
  };
  try {
    const response = UrlFetchApp.fetch(url, options);
    if (response.getResponseCode() === 204) {
      ui.alert('Success', successMsg, ui.ButtonSet.OK);
    } else {
      ui.alert('Error', `GitHub responded with code: ${response.getResponseCode()}\n\n${response.getContentText()}`, ui.ButtonSet.OK);
    }
  } catch (e) {
    ui.alert('Error', `An error occurred: ${e.toString()}`, ui.ButtonSet.OK);
  }
}

// ---------------------------------------------------------------------------
// Wager Tracker Setup
// ---------------------------------------------------------------------------
function setupWagerTracker() {
  const ss    = SpreadsheetApp.getActiveSpreadsheet();
  const ws    = ss.getSheetByName('Wager_Tracker');
  const terms = ss.getSheetByName('Terminology_Ranges');
  const ui    = SpreadsheetApp.getUi();

  if (!ws)    { ui.alert('Error', 'Wager_Tracker tab not found. Trigger a run first.', ui.ButtonSet.OK); return; }
  if (!terms) { ui.alert('Error', 'Terminology_Ranges tab not found. Trigger a run first.', ui.ButtonSet.OK); return; }

  ws.getRange('A1').setValue('Kelly Criterion Betting:').setFontWeight('bold');
  ws.getRange('B1').clearContent().insertCheckboxes();
  ws.getRange('C1').setFormula(
    '=IF(B1=FALSE,"Kelly Criterion turned off",IF(D1="","Add Bankroll amount to cell D1","Kelly active \u2014 unit size in E1"))'
  ).setFontStyle('italic');
  ws.getRange('D1').setNote('Enter your current bankroll here when Kelly Criterion is enabled.');
  ws.getRange('E1').setFormula('=IF(AND(B1=TRUE,D1<>""),TEXT(D1*0.025,"$#,##0.00"),"")');
  ws.setFrozenRows(2);

  const dataStartRow = 3;
  const lastRow      = 1000;

  const venueRule = SpreadsheetApp.newDataValidation()
    .requireValueInList(['Home', 'Away'], true).setAllowInvalid(false).build();
  ws.getRange(dataStartRow, 3, lastRow - dataStartRow + 1, 1).setDataValidation(venueRule);

  const termColB      = terms.getRange('B2:B300').getValues();
  const lastPlayerRow = termColB.filter(r => r[0] !== '').length + 1;
  if (lastPlayerRow > 1) {
    const playerRule = SpreadsheetApp.newDataValidation()
      .requireValueInRange(terms.getRange(2, 2, lastPlayerRow, 1), true).setAllowInvalid(true).build();
    ws.getRange(dataStartRow, 4, lastRow - dataStartRow + 1, 1).setDataValidation(playerRule);
  }

  const termColH      = terms.getRange('H2:H50').getValues();
  const lastMarketRow = termColH.filter(r => r[0] !== '').length + 1;
  if (lastMarketRow > 1) {
    const marketRule = SpreadsheetApp.newDataValidation()
      .requireValueInRange(terms.getRange(2, 8, lastMarketRow, 1), true).setAllowInvalid(true).build();
    ws.getRange(dataStartRow, 5, lastRow - dataStartRow + 1, 1).setDataValidation(marketRule);
  }

  const pickRule = SpreadsheetApp.newDataValidation()
    .requireValueInList(['Over', 'Under', 'Home', 'Away', 'Yes', 'No'], true).setAllowInvalid(true).build();
  ws.getRange(dataStartRow, 7, lastRow - dataStartRow + 1, 1).setDataValidation(pickRule);

  ws.getRange(dataStartRow, 6,  lastRow - dataStartRow + 1, 1).setNumberFormat('0.0');
  ws.getRange(dataStartRow, 8,  lastRow - dataStartRow + 1, 1).setNumberFormat('+0;-0');
  ws.getRange(dataStartRow, 9,  lastRow - dataStartRow + 1, 1).setNumberFormat('$#,##0.00');
  ws.getRange(dataStartRow, 12, lastRow - dataStartRow + 1, 1).setNumberFormat('$#,##0.00');
  ws.getRange(dataStartRow, 13, lastRow - dataStartRow + 1, 1).setNumberFormat('$#,##0.00');
  ws.getRange('A2:M2').setFontWeight('bold').setBackground('#f0f0f0');

  ui.alert('Done!',
    'Wager Tracker is ready.\n\n' +
    '\u2022 Check B1 and enter a bankroll in D1 to activate Kelly Criterion.\n' +
    '\u2022 Column D dropdown contains all active VGK players + VGK.\n' +
    '\u2022 Column E dropdown contains all market types from Terminology_Ranges.',
    ui.ButtonSet.OK);
}

// ---------------------------------------------------------------------------
// Update Wager Search
// ---------------------------------------------------------------------------
function updateWagerSearch() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const ui = SpreadsheetApp.getUi();
  const wt = ss.getSheetByName('Wager_Tracker');

  if (!wt) { ui.alert('Error', 'Wager_Tracker tab not found.', ui.ButtonSet.OK); return; }

  // Find or rename existing Wager Search tab
  let ws = ss.getSheetByName('Wager Search');
  if (!ws) {
    // Try common old names
    const oldNames = ['Wager_Search', 'WagerSearch', 'Wager Search'];
    for (const name of oldNames) {
      const found = ss.getSheetByName(name);
      if (found && name !== 'Wager Search') { found.setName('Wager Search'); ws = found; break; }
      if (found) { ws = found; break; }
    }
    if (!ws) ws = ss.insertSheet('Wager Search');
  }

  const allValues = wt.getDataRange().getValues();
  if (allValues.length < 3) { ui.alert('No data in Wager_Tracker.', ui.ButtonSet.OK); return; }

  const headers   = allValues[1];            // row 2
  const dataRows  = allValues.slice(2);      // row 3+
  const resultIdx = headers.indexOf('Result');
  const gameIdIdx = headers.indexOf('Game_ID');

  const openWagers = dataRows.filter(row => {
    const result = resultIdx >= 0 ? String(row[resultIdx]).trim() : '';
    const gameId = gameIdIdx >= 0 ? String(row[gameIdIdx]).trim() : '';
    return gameId && !result;
  });

  ws.clearContents();
  ws.getRange(1, 1, 1, headers.length).setValues([headers]).setFontWeight('bold').setBackground('#f0f0f0');
  if (openWagers.length > 0) {
    ws.getRange(2, 1, openWagers.length, headers.length).setValues(openWagers);
  }
  ws.setFrozenRows(1);
  ss.setActiveSheet(ws);

  ui.alert('Wager Search updated.',
    `${openWagers.length} open wager(s) synced to the Wager Search tab.`,
    ui.ButtonSet.OK);
}

// ---------------------------------------------------------------------------
// Print Open Wagers
// ---------------------------------------------------------------------------
function printOpenWagers() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const ui = SpreadsheetApp.getUi();
  const wt = ss.getSheetByName('Wager_Tracker');

  if (!wt) { ui.alert('Error', 'Wager_Tracker tab not found.', ui.ButtonSet.OK); return; }

  const allValues = wt.getDataRange().getValues();
  if (allValues.length < 3) { ui.alert('No wagers found.', ui.ButtonSet.OK); return; }

  const headers   = allValues[1];
  const dataRows  = allValues.slice(2);

  const idx = {};
  ['Game_ID','Date','Venue','Player/Team','Market','Pick','Line','Odds','Stake','Result','Grade'].forEach(h => {
    idx[h] = headers.indexOf(h);
  });

  const openWagers = dataRows.filter(row => {
    const result = idx['Result'] >= 0 ? String(row[idx['Result']]).trim() : '';
    const gameId = idx['Game_ID'] >= 0 ? String(row[idx['Game_ID']]).trim() : '';
    return gameId && !result;
  });

  if (openWagers.length === 0) {
    ui.alert('No Open Wagers', 'All bets have been graded. Nothing to print!', ui.ButtonSet.OK);
    return;
  }

  // Build wager objects with calculated potential payout
  const wagersJson = JSON.stringify(openWagers.map(row => {
    const odds  = parseFloat(idx['Odds']  >= 0 ? row[idx['Odds']]  : 0) || 0;
    const stake = parseFloat(idx['Stake'] >= 0 ? row[idx['Stake']] : 0) || 0;
    let potPayout = 0;
    if (stake > 0) {
      potPayout = odds > 0 ? stake * (odds / 100) : stake * (100 / Math.abs(odds));
    }
    return {
      gameId  : idx['Game_ID']     >= 0 ? String(row[idx['Game_ID']])     : '',
      date    : idx['Date']        >= 0 ? String(row[idx['Date']])        : '',
      venue   : idx['Venue']       >= 0 ? String(row[idx['Venue']])       : '',
      player  : idx['Player/Team'] >= 0 ? String(row[idx['Player/Team']]) : '',
      market  : idx['Market']      >= 0 ? String(row[idx['Market']])      : '',
      pick    : idx['Pick']        >= 0 ? String(row[idx['Pick']])        : '',
      line    : idx['Line']        >= 0 ? String(row[idx['Line']])        : '',
      odds    : odds,
      stake   : stake,
      potPayout: potPayout.toFixed(2)
    };
  }));

  const htmlTemplate = `
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;900&display=swap" rel="stylesheet">
<style>
  * { margin:0; padding:0; box-sizing:border-box; }

  body {
    font-family: 'Inter', sans-serif;
    background: #0d0d0d;
    color: #fff;
    padding: 20px 16px 32px;
    min-height: 100vh;
  }

  /* ── Header ── */
  .page-header {
    text-align: center;
    margin-bottom: 28px;
    padding-bottom: 16px;
    border-bottom: 1px solid #B4975A44;
  }
  .page-header .logo {
    font-size: 11px;
    letter-spacing: 6px;
    color: #B4975A;
    font-weight: 700;
    text-transform: uppercase;
    margin-bottom: 4px;
  }
  .page-header h1 {
    font-size: 26px;
    font-weight: 900;
    letter-spacing: 2px;
    color: #fff;
  }
  .page-header .subtitle {
    font-size: 11px;
    color: #555;
    margin-top: 4px;
    letter-spacing: 2px;
  }

  /* ── Ticket Grid ── */
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: 16px;
    max-width: 960px;
    margin: 0 auto;
  }

  /* ── Individual Ticket ── */
  .ticket {
    background: #161616;
    border: 1px solid #B4975A55;
    border-radius: 14px;
    overflow: hidden;
    position: relative;
  }

  .ticket-accent {
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 3px;
    background: linear-gradient(90deg, #B4975A, #f0c866, #B4975A);
  }

  .ticket-head {
    background: linear-gradient(135deg, #B4975A 0%, #7a6030 100%);
    padding: 14px 16px 10px;
  }
  .ticket-head .badge {
    display: inline-block;
    background: rgba(0,0,0,0.25);
    color: #ffe;
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
    padding: 2px 8px;
    border-radius: 20px;
    margin-bottom: 6px;
  }
  .ticket-head .player {
    font-size: 18px;
    font-weight: 900;
    color: #000;
    letter-spacing: 0.5px;
    line-height: 1.1;
    text-transform: uppercase;
  }
  .ticket-head .market {
    font-size: 11px;
    color: #333;
    font-weight: 600;
    margin-top: 2px;
  }

  /* ── Dashed Divider ── */
  .tear {
    height: 1px;
    border-top: 1px dashed #B4975A55;
    margin: 0 16px;
    position: relative;
  }
  .tear::before, .tear::after {
    content: '';
    position: absolute;
    top: -8px;
    width: 14px; height: 14px;
    background: #0d0d0d;
    border: 1px solid #B4975A55;
    border-radius: 50%;
  }
  .tear::before { left: -23px; }
  .tear::after  { right: -23px; }

  /* ── Body Rows ── */
  .ticket-body { padding: 12px 16px 4px; }
  .row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 5px 0;
    border-bottom: 1px solid #222;
  }
  .row:last-child { border-bottom: none; }
  .row .lbl {
    font-size: 10px;
    color: #666;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    font-weight: 600;
  }
  .row .val {
    font-size: 14px;
    font-weight: 600;
    color: #ddd;
  }
  .row .val.pick   { color: #fff; font-weight: 700; font-size: 15px; }
  .row .val.odds   { color: #B4975A; font-weight: 800; font-size: 16px; }

  /* ── Footer ── */
  .ticket-foot {
    background: #111;
    margin: 12px 0 0;
    padding: 12px 16px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-top: 1px solid #222;
  }
  .ticket-foot .stake-lbl { font-size: 10px; color: #555; text-transform: uppercase; letter-spacing: 1px; }
  .ticket-foot .stake-val { font-size: 13px; font-weight: 700; color: #aaa; }
  .ticket-foot .payout-block { text-align: right; }
  .ticket-foot .payout-lbl  { font-size: 10px; color: #555; text-transform: uppercase; letter-spacing: 1px; }
  .ticket-foot .payout-val  { font-size: 20px; font-weight: 900; color: #4ade80; }

  .game-chip {
    font-size: 9px;
    color: #555;
    letter-spacing: 1px;
    padding: 6px 16px 10px;
  }

  /* ── Print Button ── */
  .print-bar {
    text-align: center;
    margin: 32px 0 8px;
  }
  .print-btn {
    background: linear-gradient(135deg, #B4975A, #d4b06a);
    color: #000;
    border: none;
    padding: 13px 40px;
    font-size: 13px;
    font-weight: 800;
    border-radius: 8px;
    cursor: pointer;
    letter-spacing: 3px;
    text-transform: uppercase;
    box-shadow: 0 4px 20px #B4975A44;
    transition: transform 0.1s, box-shadow 0.1s;
  }
  .print-btn:hover {
    transform: translateY(-1px);
    box-shadow: 0 6px 24px #B4975A66;
  }
  .print-btn:active { transform: translateY(0); }
  .count-note {
    font-size: 11px;
    color: #444;
    margin-top: 10px;
    letter-spacing: 1px;
  }

  /* ── Print Styles ── */
  @media print {
    body { background: #fff; color: #000; padding: 12px; }
    .ticket { background: #fff; border: 1.5px solid #B4975A; page-break-inside: avoid; }
    .ticket-accent { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .ticket-head   { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .ticket-foot   { background: #f5f5f5; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .row .val.odds  { color: #8a6820; }
    .ticket-foot .payout-val { color: #1a7a3a; }
    .print-bar { display: none !important; }
    .page-header { border-bottom-color: #B4975A; }
    .tear::before, .tear::after { background: #fff; }
  }
</style>
</head>
<body>

<div class="page-header">
  <div class="logo">&#9830; VGK EDGE</div>
  <h1>OPEN WAGERS</h1>
  <div class="subtitle">PENDING RESULTS &mdash; <span id="gen-date"></span></div>
</div>

<div class="grid" id="ticket-grid"></div>

<div class="print-bar">
  <button class="print-btn" onclick="window.print()">&#128438; Print Tickets</button>
  <div class="count-note" id="count-note"></div>
</div>

<script>
const wagers = ${wagersJson};

function fmtOdds(o) {
  return o > 0 ? '+' + o : String(o);
}
function fmtMoney(v) {
  return '$' + parseFloat(v).toFixed(2);
}

document.getElementById('gen-date').textContent = new Date().toLocaleDateString('en-US', {month:'short',day:'numeric',year:'numeric'});
document.getElementById('count-note').textContent = wagers.length + ' open bet' + (wagers.length !== 1 ? 's' : '') + ' pending';

const grid = document.getElementById('ticket-grid');

wagers.forEach(w => {
  const t = document.createElement('div');
  t.className = 'ticket';
  t.innerHTML = \`
    <div class="ticket-accent"></div>
    <div class="ticket-head">
      <div class="badge">Open &bull; Pending</div>
      <div class="player">\${w.player || '—'}</div>
      <div class="market">\${w.market || '—'}</div>
    </div>
    <div class="tear"></div>
    <div class="ticket-body">
      <div class="row"><span class="lbl">Pick</span><span class="val pick">\${w.pick || '—'}</span></div>
      <div class="row"><span class="lbl">Line</span><span class="val">\${w.line !== '' ? w.line : '—'}</span></div>
      <div class="row"><span class="lbl">Odds</span><span class="val odds">\${fmtOdds(w.odds)}</span></div>
    </div>
    <div class="ticket-foot">
      <div>
        <div class="stake-lbl">Stake</div>
        <div class="stake-val">\${fmtMoney(w.stake)}</div>
      </div>
      <div class="payout-block">
        <div class="payout-lbl">To Win</div>
        <div class="payout-val">\${fmtMoney(w.potPayout)}</div>
      </div>
    </div>
    <div class="game-chip">GAME \${w.gameId}\${w.date ? ' &mdash; ' + w.date : ''}\${w.venue ? ' &mdash; ' + w.venue : ''}</div>
  \`;
  grid.appendChild(t);
});
</script>
</body>
</html>`;

  const output = HtmlService.createHtmlOutput(htmlTemplate)
    .setWidth(900)
    .setHeight(650)
    .setTitle('Open Wagers');

  SpreadsheetApp.getUi().showModalDialog(output, `Open Wagers (${openWagers.length})`);
}
