/**
 * VGK EDGE SIM - Google Sheets Apps Script
 *
 * Instructions:
 * 1. Open your Google Sheet.
 * 2. Click Extensions -> Apps Script.
 * 3. Delete any code there, paste this entire file, and click Save (the disk icon).
 * 4. Refresh your Google Sheet. You will see a new "VGK EDGE" menu at the top.
 * 5. On first run, click VGK EDGE -> Setup Wager Tracker to wire up dropdowns and Kelly controls.
 */

const GITHUB_OWNER   = "BradR98";
const GITHUB_REPO    = "vgk-edge-sim";
const SIM_WORKFLOW   = "Auto_2_Sim.yml";
const GRADE_WORKFLOW = "Auto_3_PostGame.yml";
// Token stored in: Extensions -> Apps Script -> Project Settings -> Script Properties
// Key: NHL Team X Team Edge
const GITHUB_PAT = PropertiesService.getScriptProperties().getProperty('NHL Team X Team Edge');

// ---------------------------------------------------------------------------
// Menu
// ---------------------------------------------------------------------------
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('VGK EDGE')
    .addItem('Run Manual Update',    'triggerSim')
    .addItem('Grade Wagers',         'triggerGradeWagers')
    .addSeparator()
    .addItem('Setup Wager Tracker',  'setupWagerTracker')
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
      "Could not find the GitHub Token. Add it to Project Settings -> Script Properties with the key 'NHL Team X Team Edge'.",
      ui.ButtonSet.OK);
    return;
  }

  const url = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/actions/workflows/${workflowId}/dispatches`;
  const options = {
    method: 'post',
    headers: {
      Authorization: `Bearer ${GITHUB_PAT}`,
      Accept: 'application/vnd.github.v3+json'
    },
    payload: JSON.stringify({ ref: 'master' }),
    muteHttpExceptions: true
  };

  try {
    const response = UrlFetchApp.fetch(url, options);
    if (response.getResponseCode() === 204) {
      ui.alert('Success', successMsg, ui.ButtonSet.OK);
    } else {
      ui.alert('Error',
        `GitHub responded with code: ${response.getResponseCode()}\n\n${response.getContentText()}`,
        ui.ButtonSet.OK);
    }
  } catch (e) {
    ui.alert('Error', `An error occurred: ${e.toString()}`, ui.ButtonSet.OK);
  }
}

// ---------------------------------------------------------------------------
// Wager Tracker Setup
// ---------------------------------------------------------------------------
function setupWagerTracker() {
  const ss   = SpreadsheetApp.getActiveSpreadsheet();
  const ws   = ss.getSheetByName('Wager_Tracker');
  const terms = ss.getSheetByName('Terminology_Ranges');
  const ui   = SpreadsheetApp.getUi();

  if (!ws) {
    ui.alert('Error', 'Wager_Tracker tab not found. Trigger a run first so the engine creates it.', ui.ButtonSet.OK);
    return;
  }
  if (!terms) {
    ui.alert('Error', 'Terminology_Ranges tab not found. Trigger a run first so the engine creates it.', ui.ButtonSet.OK);
    return;
  }

  // --- Row 1: Kelly Criterion Controls ---

  // A1: Label (bold)
  ws.getRange('A1').setValue('Kelly Criterion Betting:')
    .setFontWeight('bold');

  // B1: Checkbox
  ws.getRange('B1').clearContent();
  ws.getRange('B1').insertCheckboxes();

  // C1: Status formula
  ws.getRange('C1').setFormula(
    '=IF(B1=FALSE,"Kelly Criterion turned off",IF(D1="","Add Bankroll amount to cell D1","Kelly active \u2014 unit size in E1"))'
  ).setFontStyle('italic');

  // D1: Bankroll label hint (user fills the value)
  ws.getRange('D1').setNote('Enter your current bankroll here when Kelly Criterion is enabled.');

  // E1: Unit size formula (2.5% of bankroll as base unit)
  ws.getRange('E1').setFormula(
    '=IF(AND(B1=TRUE,D1<>""),TEXT(D1*0.025,"$#,##0.00"),"")'
  );

  // Freeze row 1 and 2 (Kelly + Headers)
  ws.setFrozenRows(2);

  // --- Column Dropdowns (rows 3 onwards) ---
  const dataStartRow = 3;
  const lastRow      = 1000;

  // C: Venue
  const venueRule = SpreadsheetApp.newDataValidation()
    .requireValueInList(['Home', 'Away'], true)
    .setAllowInvalid(false)
    .build();
  ws.getRange(dataStartRow, 3, lastRow - dataStartRow + 1, 1).setDataValidation(venueRule);

  // D: Player/Team — sourced from Terminology_Ranges column B (Full_Name + VGK)
  // Find the last non-empty row in column B of Terminology_Ranges
  const termColB = terms.getRange('B2:B300').getValues();
  const lastPlayerRow = termColB.filter(r => r[0] !== '').length + 1; // +1 for header
  if (lastPlayerRow > 1) {
    const playerRange = terms.getRange(2, 2, lastPlayerRow, 1); // B2:B{lastPlayerRow+1}
    const playerRule = SpreadsheetApp.newDataValidation()
      .requireValueInRange(playerRange, true)
      .setAllowInvalid(true) // allow manual entry of other team abbreviations
      .build();
    ws.getRange(dataStartRow, 4, lastRow - dataStartRow + 1, 1).setDataValidation(playerRule);
  }

  // E: Market — sourced from Terminology_Ranges column H (Display_Name)
  const termColH = terms.getRange('H2:H50').getValues();
  const lastMarketRow = termColH.filter(r => r[0] !== '').length + 1;
  if (lastMarketRow > 1) {
    const marketRange = terms.getRange(2, 8, lastMarketRow, 1); // H2:H{lastMarketRow+1}
    const marketRule = SpreadsheetApp.newDataValidation()
      .requireValueInRange(marketRange, true)
      .setAllowInvalid(true) // allow sportsbook aliases that haven't been mapped yet
      .build();
    ws.getRange(dataStartRow, 5, lastRow - dataStartRow + 1, 1).setDataValidation(marketRule);
  }

  // G: Pick
  const pickRule = SpreadsheetApp.newDataValidation()
    .requireValueInList(['Over', 'Under', 'Home', 'Away', 'Yes', 'No'], true)
    .setAllowInvalid(true) // allow numeric correct scores, etc.
    .build();
  ws.getRange(dataStartRow, 7, lastRow - dataStartRow + 1, 1).setDataValidation(pickRule);

  // --- Column Formatting ---
  // F: Line, H: Odds, I: Stake, L: Payout, M: Running P&L
  ws.getRange(dataStartRow, 6,  lastRow - dataStartRow + 1, 1).setNumberFormat('0.0');   // Line
  ws.getRange(dataStartRow, 8,  lastRow - dataStartRow + 1, 1).setNumberFormat('+0;-0'); // Odds
  ws.getRange(dataStartRow, 9,  lastRow - dataStartRow + 1, 1).setNumberFormat('$#,##0.00'); // Stake
  ws.getRange(dataStartRow, 12, lastRow - dataStartRow + 1, 1).setNumberFormat('$#,##0.00'); // Payout
  ws.getRange(dataStartRow, 13, lastRow - dataStartRow + 1, 1).setNumberFormat('$#,##0.00'); // Running P&L

  // Bold header row
  ws.getRange('A2:M2').setFontWeight('bold').setBackground('#f0f0f0');

  ui.alert('Done!',
    'Wager Tracker is ready.\n\n' +
    '\u2022 Check the box in B1 and enter a bankroll in D1 to activate Kelly Criterion.\n' +
    '\u2022 Column D dropdown contains all active VGK players + VGK.\n' +
    '\u2022 Column E dropdown contains all market types from Terminology_Ranges.',
    ui.ButtonSet.OK);
}
