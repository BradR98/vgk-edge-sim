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
    .addItem('Print Open Wagers',   'printOpenWagers')
    .addItem('Print Winners 🏆', 'printWinners')
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
    const oldNames = ['Wager_Search', 'WagerSearch'];
    for (const name of oldNames) {
      const found = ss.getSheetByName(name);
      if (found) { found.setName('Wager Search'); ws = found; break; }
    }
    if (!ws) ws = ss.insertSheet('Wager Search');
  }

  const allValues = wt.getDataRange().getValues();
  if (allValues.length < 3) { ui.alert('No data in Wager_Tracker.', ui.ButtonSet.OK); return; }

  const headers   = allValues[1];
  const dataRows  = allValues.slice(2);
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

  const headers  = allValues[1];
  const dataRows = allValues.slice(2);

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

  const wagersJson = JSON.stringify(openWagers.map(row => {
    const odds  = parseFloat(idx['Odds']  >= 0 ? row[idx['Odds']]  : 0) || 0;
    const stake = parseFloat(idx['Stake'] >= 0 ? row[idx['Stake']] : 0) || 0;
    let potPayout = 0;
    if (stake > 0) {
      potPayout = odds > 0 ? stake * (odds / 100) : stake * (100 / Math.abs(odds));
    }
    return {
      gameId   : idx['Game_ID']     >= 0 ? String(row[idx['Game_ID']])     : '',
      date     : idx['Date']        >= 0 ? String(row[idx['Date']])        : '',
      venue    : idx['Venue']       >= 0 ? String(row[idx['Venue']])       : '',
      player   : idx['Player/Team'] >= 0 ? String(row[idx['Player/Team']]) : '',
      market   : idx['Market']      >= 0 ? String(row[idx['Market']])      : '',
      pick     : idx['Pick']        >= 0 ? String(row[idx['Pick']])        : '',
      line     : idx['Line']        >= 0 ? String(row[idx['Line']])        : '',
      odds     : odds,
      stake    : stake,
      potPayout: potPayout.toFixed(2)
    };
  }));

  const htmlTemplate = `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;900&display=swap" rel="stylesheet">
<style>
  @page { size: letter portrait; margin: 0.35in; }
  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    font-family: 'Inter', sans-serif;
    background: #fff;
    color: #111;
    padding: 14px;
  }

  /* ── Page header ── */
  .page-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 2.5px solid #B4975A;
    padding-bottom: 7px;
    margin-bottom: 12px;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }
  .logo {
    font-size: 16px;
    font-weight: 900;
    color: #B4975A;
    letter-spacing: 3px;
    text-transform: uppercase;
  }
  .meta {
    font-size: 9px;
    color: #999;
    text-align: right;
    line-height: 1.5;
    letter-spacing: 0.5px;
  }
  .meta strong { color: #333; }

  /* ── 3-column grid: 2 rows × 3 cols = 6 per page ── */
  .grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 9px;
  }

  /* ── Ticket shell ── */
  .ticket {
    border: 1.5px solid #B4975A;
    border-radius: 7px;
    overflow: hidden;
    page-break-inside: avoid;
    break-inside: avoid;
  }

  /* Gold shimmer stripe */
  .stripe {
    height: 4px;
    background: linear-gradient(90deg, #8a6820, #e8c97a, #B4975A, #e8c97a, #8a6820);
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }

  /* Player + market header */
  .t-head {
    background: #faf7f0;
    border-left: 4px solid #B4975A;
    padding: 7px 9px 5px;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }
  .t-head .player {
    font-size: 12px;
    font-weight: 900;
    color: #111;
    text-transform: uppercase;
    letter-spacing: 0.2px;
    line-height: 1.2;
  }
  .t-head .market {
    font-size: 8.5px;
    color: #888;
    font-weight: 600;
    margin-top: 1px;
    text-transform: uppercase;
    letter-spacing: 0.4px;
  }

  /* Dashed tear */
  .tear { border-top: 1px dashed #d4c9a8; margin: 0 9px; }

  /* Data rows */
  .t-body { padding: 5px 9px 2px; }
  .row {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    padding: 2.5px 0;
    border-bottom: 1px solid #f2f2f2;
  }
  .row:last-child { border-bottom: none; }
  .lbl {
    font-size: 7.5px;
    color: #bbb;
    text-transform: uppercase;
    letter-spacing: 1px;
    font-weight: 700;
  }
  .val        { font-size: 11px; font-weight: 700; color: #222; }
  .val.pick   { font-size: 12px; color: #111; font-weight: 900; }
  .val.odds   { color: #8a6820; font-size: 12px; font-weight: 900; }

  /* Stake / To Win footer */
  .t-foot {
    background: #f7f4ec;
    padding: 5px 9px 6px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-top: 1px solid #e5dbc4;
    margin-top: 3px;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }
  .stake-lbl  { font-size: 7.5px; color: #bbb; text-transform: uppercase; letter-spacing: 1px; }
  .stake-val  { font-size: 11px; font-weight: 700; color: #666; }
  .payout-lbl { font-size: 7.5px; color: #bbb; text-transform: uppercase; letter-spacing: 1px; text-align: right; }
  .payout-val { font-size: 15px; font-weight: 900; color: #1a6e35; text-align: right; }

  /* Game ID footer chip */
  .chip {
    font-size: 7px;
    color: #ccc;
    letter-spacing: 0.5px;
    padding: 3px 9px 5px;
  }

  /* Print button */
  .print-bar { text-align: center; margin: 16px 0 4px; }
  .print-btn {
    background: #B4975A;
    color: #fff;
    border: none;
    padding: 9px 28px;
    font-size: 11px;
    font-weight: 800;
    border-radius: 6px;
    cursor: pointer;
    letter-spacing: 2px;
    text-transform: uppercase;
  }
  .print-btn:hover { background: #9a7d40; }

  @media print {
    .print-bar { display: none !important; }
    body { padding: 0; }
  }
</style>
</head>
<body>

<div class="page-header">
  <div class="logo">&#9830; VGK Edge &mdash; Open Wagers</div>
  <div class="meta">
    Printed <strong id="gen-date"></strong><br>
    <span id="bet-count"></span>
  </div>
</div>

<div class="grid" id="grid"></div>

<div class="print-bar">
  <button class="print-btn" onclick="window.print()">&#128438;&nbsp; Print</button>
</div>

<script>
const wagers = ${wagersJson};

const fmtOdds  = o => o > 0 ? '+' + o : String(o);
const fmtMoney = v => '$' + parseFloat(v).toFixed(2);

document.getElementById('gen-date').textContent =
  new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
document.getElementById('bet-count').textContent =
  wagers.length + ' open bet' + (wagers.length !== 1 ? 's' : '');

const grid = document.getElementById('grid');
wagers.forEach(w => {
  const t = document.createElement('div');
  t.className = 'ticket';
  t.innerHTML = \`
    <div class="stripe"></div>
    <div class="t-head">
      <div class="player">\${w.player || '&mdash;'}</div>
      <div class="market">\${w.market || '&mdash;'}</div>
    </div>
    <div class="tear"></div>
    <div class="t-body">
      <div class="row"><span class="lbl">Pick</span><span class="val pick">\${w.pick || '&mdash;'}</span></div>
      <div class="row"><span class="lbl">Line</span><span class="val">\${w.line !== '' ? w.line : '&mdash;'}</span></div>
      <div class="row"><span class="lbl">Odds</span><span class="val odds">\${fmtOdds(w.odds)}</span></div>
    </div>
    <div class="t-foot">
      <div>
        <div class="stake-lbl">Stake</div>
        <div class="stake-val">\${fmtMoney(w.stake)}</div>
      </div>
      <div>
        <div class="payout-lbl">To Win</div>
        <div class="payout-val">\${fmtMoney(w.potPayout)}</div>
      </div>
    </div>
    <div class="chip">GAME \${w.gameId}\${w.date ? ' &mdash; ' + w.date : ''}\${w.venue ? ' &mdash; ' + w.venue : ''}</div>
  \`;
  grid.appendChild(t);
});
</script>
</body>
</html>`;

  const output = HtmlService.createHtmlOutput(htmlTemplate)
    .setWidth(900)
    .setHeight(640)
    .setTitle('Open Wagers');

  SpreadsheetApp.getUi().showModalDialog(output, `Open Wagers (${openWagers.length})`);
}
// ---------------------------------------------------------------------------
// Print Winners
// ---------------------------------------------------------------------------
function printWinners() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const ui = SpreadsheetApp.getUi();
  const wt = ss.getSheetByName('Wager_Tracker');

  if (!wt) { ui.alert('Error', 'Wager_Tracker tab not found.', ui.ButtonSet.OK); return; }

  const allValues = wt.getDataRange().getValues();
  if (allValues.length < 3) { ui.alert('No wagers found.', ui.ButtonSet.OK); return; }

  const headers  = allValues[1];
  const dataRows = allValues.slice(2);

  const idx = {};
  ['Game_ID','Date','Venue','Player/Team','Market','Pick','Line','Odds','Stake','Result','Grade','Payout'].forEach(h => {
    idx[h] = headers.indexOf(h);
  });

  const winners = dataRows.filter(row => {
    const grade  = idx['Grade']   >= 0 ? String(row[idx['Grade']]).trim().toUpperCase()  : '';
    const gameId = idx['Game_ID'] >= 0 ? String(row[idx['Game_ID']]).trim() : '';
    return gameId && grade === 'WIN';
  });

  if (winners.length === 0) {
    ui.alert('No Winners Yet', 'No graded winning wagers found. Go place some bets!', ui.ButtonSet.OK);
    return;
  }

  const wagersJson = JSON.stringify(winners.map(row => {
    const odds   = parseFloat(idx['Odds']   >= 0 ? row[idx['Odds']]   : 0) || 0;
    const stake  = parseFloat(idx['Stake']  >= 0 ? row[idx['Stake']]  : 0) || 0;
    const payout = parseFloat(idx['Payout'] >= 0 ? row[idx['Payout']] : 0) || 0;
    const result = idx['Result'] >= 0 ? String(row[idx['Result']]) : '';
    return {
      gameId : idx['Game_ID']     >= 0 ? String(row[idx['Game_ID']])     : '',
      date   : idx['Date']        >= 0 ? String(row[idx['Date']])        : '',
      venue  : idx['Venue']       >= 0 ? String(row[idx['Venue']])       : '',
      player : idx['Player/Team'] >= 0 ? String(row[idx['Player/Team']]) : '',
      market : idx['Market']      >= 0 ? String(row[idx['Market']])      : '',
      pick   : idx['Pick']        >= 0 ? String(row[idx['Pick']])        : '',
      line   : idx['Line']        >= 0 ? String(row[idx['Line']])        : '',
      odds, stake, payout, result
    };
  }));

  const html = `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;900&display=swap" rel="stylesheet">
<style>
  @page { size: letter portrait; margin: 0.35in; }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family:'Inter',sans-serif; background:#fff; color:#111; padding:14px; }

  .page-header {
    display:flex; justify-content:space-between; align-items:center;
    border-bottom:2.5px solid #1a6e35; padding-bottom:7px; margin-bottom:12px;
    -webkit-print-color-adjust:exact; print-color-adjust:exact;
  }
  .logo { font-size:16px; font-weight:900; color:#1a6e35; letter-spacing:3px; text-transform:uppercase; }
  .meta { font-size:9px; color:#999; text-align:right; line-height:1.5; }
  .meta strong { color:#333; }

  .grid { display:grid; grid-template-columns:repeat(3,1fr); gap:9px; }

  /* Ticket */
  .ticket {
    border:1.5px solid #1a6e35; border-radius:7px; overflow:hidden;
    page-break-inside:avoid; break-inside:avoid; position:relative;
  }

  /* Green shimmer stripe */
  .stripe {
    height:4px;
    background:linear-gradient(90deg,#0f4a23,#4ade80,#1a6e35,#4ade80,#0f4a23);
    -webkit-print-color-adjust:exact; print-color-adjust:exact;
  }

  /* WINNER! diagonal stamp */
  .stamp {
    position:absolute;
    top:50%; left:50%;
    transform:translate(-50%,-50%) rotate(-28deg);
    font-size:26px; font-weight:900; letter-spacing:5px;
    color:rgba(26,110,53,0.18);
    border:3px solid rgba(26,110,53,0.18);
    border-radius:4px; padding:3px 10px;
    text-transform:uppercase; white-space:nowrap;
    pointer-events:none; user-select:none;
    -webkit-print-color-adjust:exact; print-color-adjust:exact;
  }

  .t-head {
    background:#f2faf5; border-left:4px solid #1a6e35;
    padding:7px 9px 5px;
    -webkit-print-color-adjust:exact; print-color-adjust:exact;
  }
  .t-head .player { font-size:12px; font-weight:900; color:#111; text-transform:uppercase; line-height:1.2; }
  .t-head .market { font-size:8.5px; color:#888; font-weight:600; margin-top:1px; text-transform:uppercase; letter-spacing:0.4px; }

  .tear { border-top:1px dashed #b2dfc0; margin:0 9px; }

  .t-body { padding:5px 9px 2px; }
  .row { display:flex; justify-content:space-between; align-items:baseline; padding:2.5px 0; border-bottom:1px solid #f2f2f2; }
  .row:last-child { border-bottom:none; }
  .lbl { font-size:7.5px; color:#bbb; text-transform:uppercase; letter-spacing:1px; font-weight:700; }
  .val      { font-size:11px; font-weight:700; color:#222; }
  .val.pick { font-size:12px; font-weight:900; color:#111; }
  .val.odds { color:#1a6e35; font-size:12px; font-weight:900; }
  .val.result { font-size:11px; color:#555; }

  .t-foot {
    background:#edf7f1; padding:5px 9px 6px;
    display:flex; justify-content:space-between; align-items:center;
    border-top:1px solid #b2dfc0; margin-top:3px;
    -webkit-print-color-adjust:exact; print-color-adjust:exact;
  }
  .stake-lbl  { font-size:7.5px; color:#bbb; text-transform:uppercase; letter-spacing:1px; }
  .stake-val  { font-size:11px; font-weight:700; color:#666; }
  .payout-lbl { font-size:7.5px; color:#1a6e35; text-transform:uppercase; letter-spacing:1px; font-weight:700; text-align:right; }
  .payout-val { font-size:16px; font-weight:900; color:#1a6e35; text-align:right; }

  .chip { font-size:7px; color:#ccc; letter-spacing:0.5px; padding:3px 9px 5px; }

  .print-bar { text-align:center; margin:16px 0 4px; }
  .print-btn {
    background:#1a6e35; color:#fff; border:none; padding:9px 28px;
    font-size:11px; font-weight:800; border-radius:6px; cursor:pointer;
    letter-spacing:2px; text-transform:uppercase;
  }
  .print-btn:hover { background:#145228; }

  @media print {
    .print-bar { display:none !important; }
    body { padding:0; }
  }
</style>
</head>
<body>

<div class="page-header">
  <div class="logo">&#127942; VGK Edge &mdash; Winners</div>
  <div class="meta">Printed <strong id="gen-date"></strong><br><span id="bet-count"></span></div>
</div>

<div class="grid" id="grid"></div>

<div class="print-bar">
  <button class="print-btn" onclick="window.print()">&#128438;&nbsp; Print</button>
</div>

<script>
const wagers = ${wagersJson};
const fmtOdds  = o => o > 0 ? '+' + o : String(o);
const fmtMoney = v => '$' + parseFloat(v).toFixed(2);

document.getElementById('gen-date').textContent =
  new Date().toLocaleDateString('en-US', { month:'short', day:'numeric', year:'numeric' });
document.getElementById('bet-count').textContent =
  wagers.length + ' winning bet' + (wagers.length !== 1 ? 's' : '');

const grid = document.getElementById('grid');
wagers.forEach(w => {
  const t = document.createElement('div');
  t.className = 'ticket';
  t.innerHTML = \`
    <div class="stripe"></div>
    <div class="stamp">WINNER!</div>
    <div class="t-head">
      <div class="player">\${w.player || '&mdash;'}</div>
      <div class="market">\${w.market || '&mdash;'}</div>
    </div>
    <div class="tear"></div>
    <div class="t-body">
      <div class="row"><span class="lbl">Pick</span><span class="val pick">\${w.pick || '&mdash;'}</span></div>
      <div class="row"><span class="lbl">Line</span><span class="val">\${w.line !== '' ? w.line : '&mdash;'}</span></div>
      <div class="row"><span class="lbl">Odds</span><span class="val odds">\${fmtOdds(w.odds)}</span></div>
      <div class="row"><span class="lbl">Result</span><span class="val result">\${w.result || '&mdash;'}</span></div>
    </div>
    <div class="t-foot">
      <div><div class="stake-lbl">Staked</div><div class="stake-val">\${fmtMoney(w.stake)}</div></div>
      <div><div class="payout-lbl">&#9650; Won</div><div class="payout-val">+\${fmtMoney(w.payout)}</div></div>
    </div>
    <div class="chip">GAME \${w.gameId}\${w.date ? ' &mdash; ' + w.date : ''}\${w.venue ? ' &mdash; ' + w.venue : ''}</div>
  \`;
  grid.appendChild(t);
});
<\/script>
</body>
</html>`;

  const output = HtmlService.createHtmlOutput(html)
    .setWidth(900)
    .setHeight(640)
    .setTitle('Winners');

  SpreadsheetApp.getUi().showModalDialog(output, `Winners 🏆 (${winners.length})`);
}
