/**
 * VGK EDGE SIM - Manual Trigger
 * 
 * Instructions:
 * 1. Open your Google Sheet.
 * 2. Click Extensions -> Apps Script.
 * 3. Delete any code there, paste this entire file, and click Save (the disk icon).
 * 4. Refresh your Google Sheet. You will see a new "VGK EDGE" menu at the top.
 */

// Replace these variables with your actual GitHub details
const GITHUB_OWNER = "BradR98"; // Your GitHub username
const GITHUB_REPO = "vgk-edge-sim"; // Your repository name
const WORKFLOW_ID = "Auto_2_Sim.yml"; // The workflow file to trigger
// You must generate a Fine-grained PAT on GitHub with 'Actions: Read & Write' permission
const GITHUB_PAT = "YOUR_GITHUB_PERSONAL_ACCESS_TOKEN_HERE";

function onOpen() {
  const ui = SpreadsheetApp.getUi();
  ui.createMenu('VGK EDGE')
    .addItem('Run Manual Update', 'triggerGitHubAction')
    .addToUi();
}

function triggerGitHubAction() {
  const ui = SpreadsheetApp.getUi();
  
  if (GITHUB_PAT === "YOUR_GITHUB_PERSONAL_ACCESS_TOKEN_HERE") {
    ui.alert("Configuration Error", "You must replace 'YOUR_GITHUB_PERSONAL_ACCESS_TOKEN_HERE' with your actual GitHub token in the Apps Script editor.", ui.ButtonSet.OK);
    return;
  }

  const url = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/actions/workflows/${WORKFLOW_ID}/dispatches`;
  
  const payload = {
    "ref": "master"
  };
  
  const options = {
    "method": "post",
    "headers": {
      "Authorization": `Bearer ${GITHUB_PAT}`,
      "Accept": "application/vnd.github.v3+json"
    },
    "payload": JSON.stringify(payload),
    "muteHttpExceptions": true
  };
  
  try {
    const response = UrlFetchApp.fetch(url, options);
    const responseCode = response.getResponseCode();
    
    if (responseCode === 204) {
      ui.alert("Success", "Monte Carlo Simulation triggered! Give it about 45 seconds to crunch the numbers and automatically refresh this sheet.", ui.ButtonSet.OK);
    } else {
      ui.alert("Error", `Failed to trigger. GitHub responded with code: ${responseCode}\n\n${response.getContentText()}`, ui.ButtonSet.OK);
    }
  } catch (e) {
    ui.alert("Error", `An error occurred: ${e.toString()}`, ui.ButtonSet.OK);
  }
}
