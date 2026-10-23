/**
 * ============================================================================
 * ONESS INFRA PRIVATE LIMITED - ERP WORK ORDER BACKEND SYSTEM
 * ============================================================================
 * Handles:
 *  1. Data synchronization (Vendors, Sites, Terms, Work Order Log)
 *  2. Search & Retrieval of existing Work Orders by WO Number
 *  3. Submitting Work Orders to 'WO_Log'
 *  4. Storing 'Contractor Type' in Column B
 *  5. Generating & Saving PDF files to Google Drive
 *  6. Storing Google Drive Link in Column H and submission status in Column L
 * ============================================================================
 */

// Global Configuration
var CONFIG = {
  DRIVE_FOLDER_NAME: "Oness_WO_PDFs", // Target Google Drive folder for PDF documents
  LOGO_FILE_ID: "", // Optional Google Drive image file ID for the company logo.
  COMPANY_NAME: "ONESS INFRA PRIVATE LIMITED",
  COMPANY_DIVISION: "CONSTRUCTION & INFRASTRUCTURE ERP DIVISION",
  COMPANY_CIN: "CIN: U45201MP2022PTC062145",
  COMPANY_ADDRESS: "2nd Floor, Office No. 202, LIC Tower, Scheme No 54, Indore, Madhya Pradesh 452010",
  SHEET_NAMES: {
    VENDORS: "Vendors",
    SITES: "Sites",
    WO_LOG: "WO_Log",
    TERMS: "Terms"
  }
};

/**
 * Creates custom ERP menu inside Google Sheets for quick management
 */
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("🏗️ Oness ERP")
    .addItem("1. Initialize / Setup All Sheet Tabs & Columns", "setupSheetTemplates")
    .addItem("2. Verify Google Drive PDF Folder", "checkOrSetupDriveFolder")
    .addItem("3. Authorize PDF Generation", "authorizePdfGeneration")
    .addToUi();
}

/**
 * Automatically creates and formats all sheets if they don't already exist.
 * Run this once from the 'Oness ERP' menu in your Google Sheet!
 */
function setupSheetTemplates() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  
  // 1. Setup 'WO_Log' sheet with the complete work-order schema.
  var logSheet = ss.getSheetByName(CONFIG.SHEET_NAMES.WO_LOG);
  if (!logSheet) {
    logSheet = ss.insertSheet(CONFIG.SHEET_NAMES.WO_LOG);
  }
  ensureWorkOrderHeaders(logSheet);

  // 2. Setup 'Vendors' sheet
  var vSheet = ss.getSheetByName(CONFIG.SHEET_NAMES.VENDORS);
  if (!vSheet) {
    vSheet = ss.insertSheet(CONFIG.SHEET_NAMES.VENDORS);
  }
  if (vSheet.getLastRow() === 0) {
    var vHeaders = ["Vendor Name", "Contractor Type", "Code", "Address", "Aadhar No", "PAN No", "GST No"];
    vSheet.appendRow(vHeaders);
    vSheet.getRange(1, 1, 1, vHeaders.length)
      .setBackground("#1a2a3a")
      .setFontColor("#ffffff")
      .setFontWeight("bold");
    vSheet.setFrozenRows(1);
  }

  // 3. Setup 'Sites' sheet
  var sSheet = ss.getSheetByName(CONFIG.SHEET_NAMES.SITES);
  if (!sSheet) {
    sSheet = ss.insertSheet(CONFIG.SHEET_NAMES.SITES);
  }
  if (sSheet.getLastRow() === 0) {
    var sHeaders = ["Site Name", "Project Code", "Type", "Address", "Contact Person", "Mo. No."];
    sSheet.appendRow(sHeaders);
    sSheet.getRange(1, 1, 1, sHeaders.length)
      .setBackground("#1a2a3a")
      .setFontColor("#ffffff")
      .setFontWeight("bold");
    sSheet.setFrozenRows(1);
  }

  // 4. Setup 'Terms' sheet
  var tSheet = ss.getSheetByName(CONFIG.SHEET_NAMES.TERMS);
  if (!tSheet) {
    tSheet = ss.insertSheet(CONFIG.SHEET_NAMES.TERMS);
  }
  if (tSheet.getLastRow() === 0) {
    var tHeaders = ["Specific Terms & Conditions", "Payment Terms & Conditions", "Basic Terms & Conditions"];
    tSheet.appendRow(tHeaders);
    tSheet.getRange(1, 1, 1, tHeaders.length)
      .setBackground("#1a2a3a")
      .setFontColor("#ffffff")
      .setFontWeight("bold");
    tSheet.setFrozenRows(1);
  }

  SpreadsheetApp.getUi().alert("Setup Completed!\nAll tabs (WO_Log, Vendors, Sites, Terms) are verified and formatted.");
}

/**
 * Checks or creates the Google Drive storage folder for Work Order PDFs
 */
function checkOrSetupDriveFolder() {
  var folder = getOrCreateFolder(CONFIG.DRIVE_FOLDER_NAME);
  SpreadsheetApp.getUi().alert("Google Drive Folder Active: '" + CONFIG.DRIVE_FOLDER_NAME + "'\nFolder ID: " + folder.getId());
}

function authorizePdfGeneration() {
  var document = DocumentApp.create("Oness ERP PDF Authorization Check");
  var documentId = document.getId();
  try {
    document.getBody().appendParagraph("PDF authorization check");
    document.saveAndClose();
    DriveApp.getFileById(documentId).getAs(MimeType.PDF);
  } finally {
    DriveApp.getFileById(documentId).setTrashed(true);
  }
  SpreadsheetApp.getUi().alert("PDF generation access verified. The temporary document was moved to Trash.");
}

/**
 * Safely fetches or creates a folder in Google Drive
 */
function getOrCreateFolder(folderName) {
  var folders = DriveApp.getFoldersByName(folderName);
  if (folders.hasNext()) {
    return folders.next();
  }
  return DriveApp.createFolder(folderName);
}

/**
 * Handles incoming GET requests:
 * 1. action=getData: Returns all vendors, sites, WO history, and terms.
 * 2. action=getWorkOrder: Searches for a specific WO number in 'WO_Log'.
 */
function doGet(e) {
  try {
    var p = e.parameter || {};
    var action = p.action || "getData";
    var ss = SpreadsheetApp.getActiveSpreadsheet();

    // ACTION: Search a specific Work Order
    if (action === "getWorkOrder") {
      var searchWo = (p.woNumber || "").trim().toUpperCase();
      if (!searchWo) {
        return createJsonResponse({ success: false, error: "WO number parameter missing" });
      }

      var logSheet = ss.getSheetByName(CONFIG.SHEET_NAMES.WO_LOG);
      if (!logSheet || logSheet.getLastRow() < 2) {
        return createJsonResponse({ success: false, error: "WO_Log sheet is empty" });
      }

      var rows = sheetToObjects(logSheet);
      var matched = null;

      for (var i = 0; i < rows.length; i++) {
        var rowWo = (rows[i]["Work Order No"] || rows[i]["WO Number"] || rows[i]["woNumber"] || "").toString().trim().toUpperCase();
        if (rowWo === searchWo) {
          matched = rows[i];
          break;
        }
      }

      if (matched) {
        // Parse items and milestones safely if stored as JSON strings
        var parsedItems = [];
        var parsedMilestones = [];
        try { parsedItems = JSON.parse(matched["Item Details (JSON)"] || "[]"); } catch (e) { parsedItems = []; }
        try { parsedMilestones = JSON.parse(matched["Milestones (JSON)"] || "[]"); } catch (e) { parsedMilestones = []; }

        return createJsonResponse({
          success: true,
          record: {
            woDate: matched["Timestamp / Date"] || "",
            contractorType: matched["Contractor Type"] || "",
            contractor: matched["Contractor Name"] || "",
            site: matched["Project Site"] || "",
            woNumber: matched["Work Order No"] || searchWo,
            workType: matched["Work Type"] || "",
            amount: matched["Total Amount (₹)"] || 0,
            pdfLink: matched["PDF Drive Link"] || "",
            scopeOfWork: matched["Scope of Work"] || "",
            items: parsedItems,
            milestones: parsedMilestones,
            status: matched["Status"] || ""
          }
        });
      } else {
        return createJsonResponse({ success: false, error: "Work order not found" });
      }
    }

    // ACTION: Get initial application dataset
    var vendorsSheet = ss.getSheetByName(CONFIG.SHEET_NAMES.VENDORS);
    var sitesSheet = ss.getSheetByName(CONFIG.SHEET_NAMES.SITES);
    var woLogSheet = ss.getSheetByName(CONFIG.SHEET_NAMES.WO_LOG);
    var termsSheet = ss.getSheetByName(CONFIG.SHEET_NAMES.TERMS);

    var vendors = vendorsSheet ? sheetToObjects(vendorsSheet) : [];
    var sites = sitesSheet ? sheetToObjects(sitesSheet) : [];
    var woLog = woLogSheet ? sheetToObjects(woLogSheet) : [];
    var terms = termsSheet ? extractTerms(termsSheet) : { specific: [], payment: [], basic: [] };

    return createJsonResponse({
      success: true,
      data: {
        vendors: vendors,
        sites: sites,
        woLog: woLog,
        terms: terms
      }
    });

  } catch (err) {
    return createJsonResponse({ success: false, error: err.toString() });
  }
}

/**
 * Handles incoming POST requests to submit Work Orders.
 * Saves the generated PDF into Google Drive and updates Column B (Contractor Type) and Column H (PDF Link).
 */
function doPost(e) {
  try {
    var p = {};
    
    // Parse form parameters or JSON payload
    if (e.parameter && Object.keys(e.parameter).length > 0) {
      p = e.parameter;
    } else if (e.postData && e.postData.contents) {
      try {
        p = JSON.parse(e.postData.contents);
      } catch (ex) {
        // Fallback for form-urlencoded payload in postData
        p = parseQueryString(e.postData.contents);
      }
    }

    var action = p.action || "saveWorkOrder";
    if (action !== "saveWorkOrder") {
      return createJsonResponse({ success: false, error: "Invalid action" });
    }

    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var logSheet = ss.getSheetByName(CONFIG.SHEET_NAMES.WO_LOG);
    if (!logSheet) {
      logSheet = ss.insertSheet(CONFIG.SHEET_NAMES.WO_LOG);
    }
    ensureWorkOrderHeaders(logSheet);

    // Form parameter extractions
    var woNumber = (p.woNumber || "").trim();
    if (!woNumber || woNumber === "---") {
      woNumber = "WO-" + Utilities.formatDate(new Date(), "GMT+5:30", "yyyyMMdd-HHmmss");
    }

    var contractorName = p.contractor || p.vendor || "";
    var contractorType = (p.contractorType || p.contractor_type || "").toString().trim();
    if (!contractorType) {
      contractorType = findContractorType(ss, contractorName);
    }
    if (!contractorType) {
      contractorType = p.workType || "Labor Only";
    }
    var siteName = p.site || "";
    var workType = p.workType || "";
    var amount = parseFloat(p.amount || 0) || 0;
    var woDate = p.woDate || Utilities.formatDate(new Date(), "GMT+5:30", "dd/MM/yyyy HH:mm");
    var scopeOfWork = p.scopeOfWork || "";
    var itemsJson = JSON.stringify(parseJsonArray(p.items, "Items"));
    var milestonesJson = JSON.stringify(parseJsonArray(p.milestones, "Milestones"));
    var status = (p.status || "Submitted").toString().trim() || "Submitted";

    var pdfDriveLink = "";

    // Keep supporting clients that provide a rendered PDF.
    if (p.pdfBase64 && p.pdfBase64.length > 50) {
      var folder = getOrCreateFolder(CONFIG.DRIVE_FOLDER_NAME);
      var cleanFileName = (p.pdfFileName || (woNumber.replace(/[\/\\?%*:|"<>]/g, "_") + ".pdf"));
      
      // Remove data URL prefix if sent
      var rawBase64 = p.pdfBase64;
      if (rawBase64.indexOf(",") > -1) {
        rawBase64 = rawBase64.split(",")[1];
      }

      var decodedBytes = Utilities.base64Decode(rawBase64);
      var pdfBlob = Utilities.newBlob(decodedBytes, "application/pdf", cleanFileName);
      
      // Save file to Google Drive and configure permissions
      var driveFile = folder.createFile(pdfBlob);
      driveFile.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
      pdfDriveLink = driveFile.getUrl();
    } else {
      pdfDriveLink = createWorkOrderPdf({
        woNumber: woNumber,
        woDate: woDate,
        contractorType: contractorType,
        contractorName: contractorName,
        siteName: siteName,
        workType: workType,
        amount: amount,
        scopeOfWork: scopeOfWork,
        contractorAddress: p.contractorAddress || "",
        aadhaar: p.aadhaar || "",
        pan: p.pan || "",
        gst: p.gst || "",
        siteAddress: p.siteAddress || "",
        siteContact: p.siteContact || "",
        siteMobile: p.siteMobile || "",
        basicTerms: p.basicTerms || "",
        paymentTerms: p.paymentTerms || "",
        specificTerms: p.specificTerms || "",
        items: itemsJson,
        milestones: milestonesJson
      });
    }

    // Determine whether this WO already exists in WO_Log to update or append
    var existingRowIndex = -1;
    var lastRow = logSheet.getLastRow();

    if (lastRow > 1) {
      // Column E contains the Work Order No (Index 5)
      var woColValues = logSheet.getRange(2, 5, lastRow - 1, 1).getValues();
      for (var r = 0; r < woColValues.length; r++) {
        if (woColValues[r][0].toString().trim().toUpperCase() === woNumber.toUpperCase()) {
          existingRowIndex = r + 2; // +2 for 1-based index and header row
          break;
        }
      }
    }

    // Keep this order aligned with getWorkOrderHeaders().
    var rowData = [
      woDate,
      contractorType,
      contractorName,
      siteName,
      woNumber,
      workType,
      amount,
      pdfDriveLink,
      scopeOfWork,
      itemsJson,
      milestonesJson,
      status
    ];

    if (existingRowIndex > 0) {
      // Update existing record
      logSheet.getRange(existingRowIndex, 1, 1, rowData.length).setValues([rowData]);
    } else {
      // Append new record
      logSheet.appendRow(rowData);
    }

    return createJsonResponse({
      success: true,
      message: "Work order successfully saved to WO_Log.",
      woNumber: woNumber,
      pdfUrl: pdfDriveLink,
      status: status
    });

  } catch (err) {
    return createJsonResponse({
      success: false,
      error: err.toString()
    });
  }
}

function getWorkOrderHeaders() {
  return [
    "Timestamp / Date",
    "Contractor Type",
    "Contractor Name",
    "Project Site",
    "Work Order No",
    "Work Type",
    "Total Amount (₹)",
    "PDF Drive Link",
    "Scope of Work",
    "Item Details (JSON)",
    "Milestones (JSON)",
    "Status"
  ];
}

function ensureWorkOrderHeaders(sheet) {
  var headers = getWorkOrderHeaders();
  sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
  sheet.getRange(1, 1, 1, headers.length)
    .setBackground("#1a2a3a")
    .setFontColor("#c5a059")
    .setFontWeight("bold");
  sheet.setFrozenRows(1);
}

function findContractorType(ss, contractorName) {
  if (!contractorName) return "";
  var vendorsSheet = ss.getSheetByName(CONFIG.SHEET_NAMES.VENDORS);
  if (!vendorsSheet) return "";

  var vendors = sheetToObjects(vendorsSheet);
  var targetName = contractorName.toString().trim().toLowerCase();
  for (var i = 0; i < vendors.length; i++) {
    var name = vendors[i]["Vendor Name"] || vendors[i]["Contractor Name"] || vendors[i]["Name"] || "";
    if (name.toString().trim().toLowerCase() === targetName) {
      return (vendors[i]["Contractor Type"] || vendors[i]["Contractor type"] || "").toString().trim();
    }
  }
  return "";
}

function parseJsonArray(value, fieldName) {
  if (!value) return [];
  var parsed = Array.isArray(value) ? value : JSON.parse(value);
  if (!Array.isArray(parsed)) {
    throw new Error(fieldName + " must be an array.");
  }
  return parsed;
}

function createWorkOrderPdf(workOrder) {
  var fileName = workOrder.woNumber.replace(/[\/\\?%*:|"<>]/g, "_") + ".pdf";
  var folder = getOrCreateFolder(CONFIG.DRIVE_FOLDER_NAME);
  var document = DocumentApp.create(fileName.replace(/\.pdf$/i, ""));
  var documentId = document.getId();

  try {
    var body = document.getBody();
    body.setMarginTop(32).setMarginBottom(32).setMarginLeft(36).setMarginRight(36);
    body.setAttributes({
      [DocumentApp.Attribute.FONT_FAMILY]: "Arial",
      [DocumentApp.Attribute.FONT_SIZE]: 9,
      [DocumentApp.Attribute.FOREGROUND_COLOR]: "#1e293b"
    });

    addWorkOrderPdfHeader(body, workOrder);
    addWorkOrderDetails(body, workOrder);

    var items = parseJsonArray(workOrder.items, "Items");
    addWorkOrderItems(body, items, workOrder.amount);

    var milestones = parseJsonArray(workOrder.milestones, "Milestones");
    addWorkOrderMilestones(body, milestones, workOrder.amount);

    addWorkOrderTextSection(body, "1. SCOPE OF WORK", workOrder.scopeOfWork);
    addWorkOrderTextSection(body, "2. BASIC TERMS & CONDITIONS", workOrder.basicTerms);
    addWorkOrderTextSection(body, "3. PAYMENT TERMS & CONDITIONS", workOrder.paymentTerms);
    addWorkOrderTextSection(body, "4. SPECIFIC SITE TERMS & SAFETY", workOrder.specificTerms);
    addWorkOrderSignatures(body);
    addWorkOrderPdfFooter(body);

    document.saveAndClose();
    var pdfBlob = DriveApp.getFileById(documentId).getAs(MimeType.PDF).setName(fileName);
    var pdfFile = folder.createFile(pdfBlob);
    pdfFile.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
    return pdfFile.getUrl();
  } finally {
    DriveApp.getFileById(documentId).setTrashed(true);
  }
}

function addWorkOrderPdfHeader(body, workOrder) {
  var header = body.appendTable([["", ""]]);
  header.setBorderColor("#cbd5e1").setBorderWidth(0);
  header.setColumnWidth(0, 58).setColumnWidth(1, 465);
  var logoCell = header.getCell(0, 0);
  logoCell.setBackgroundColor("#1a2a3a");
  logoCell.setPaddingTop(8).setPaddingBottom(8).setPaddingLeft(6).setPaddingRight(6);

  if (CONFIG.LOGO_FILE_ID) {
    var logo = DriveApp.getFileById(CONFIG.LOGO_FILE_ID).getBlob();
    var image = logoCell.insertImage(0, logo);
    image.setWidth(44).setHeight(44);
  } else {
    var mark = logoCell.getChild(0).asParagraph();
    mark.setText("OI");
    mark.setAlignment(DocumentApp.HorizontalAlignment.CENTER);
    mark.editAsText().setBold(true).setFontSize(18).setForegroundColor("#c5a059");
  }

  var companyCell = header.getCell(0, 1);
  companyCell.setPaddingTop(4).setPaddingBottom(4).setPaddingLeft(12).setPaddingRight(8);
  var company = companyCell.getChild(0).asParagraph();
  company.setText(CONFIG.COMPANY_NAME);
  company.setSpacingAfter(2);
  company.editAsText().setBold(true).setFontSize(17).setForegroundColor("#1a2a3a");
  var division = companyCell.appendParagraph(CONFIG.COMPANY_DIVISION);
  division.setSpacingAfter(2);
  division.editAsText().setBold(true).setFontSize(8).setForegroundColor("#64748b");
  var cin = companyCell.appendParagraph(CONFIG.COMPANY_CIN + "  |  Registered Infrastructure Contractor");
  cin.setSpacingAfter(0);
  cin.editAsText().setFontSize(7).setForegroundColor("#94a3b8");

  var title = body.appendParagraph("WORK ORDER");
  title.setAlignment(DocumentApp.HorizontalAlignment.CENTER);
  title.setSpacingBefore(10).setSpacingAfter(8);
  title.editAsText().setBold(true).setFontSize(15).setForegroundColor("#1a2a3a");
}

function addWorkOrderDetails(body, workOrder) {
  addWorkOrderSectionTitle(body, "WORK ORDER & PROJECT DETAILS");
  var detailRows = [
    ["Work Order No.", workOrder.woNumber, "Date", workOrder.woDate],
    ["Contractor", workOrder.contractorName, "Contractor Type", workOrder.contractorType],
    ["Contractor Address", workOrder.contractorAddress, "Work Type", workOrder.workType],
    ["Aadhaar No.", workOrder.aadhaar, "PAN", workOrder.pan],
    ["GSTIN No.", workOrder.gst, "Project Site", workOrder.siteName],
    ["Site Address", workOrder.siteAddress, "Site Incharge", workOrder.siteContact],
    ["Mobile", workOrder.siteMobile, "Total Work Value", formatRupees(workOrder.amount)]
  ];
  var table = body.appendTable(detailRows);
  styleWorkOrderTable(table, false);
  table.setColumnWidth(0, 78).setColumnWidth(1, 185).setColumnWidth(2, 78).setColumnWidth(3, 182);
  for (var r = 0; r < table.getNumRows(); r++) {
    for (var c = 0; c < table.getRow(r).getNumCells(); c++) {
      var cell = table.getCell(r, c);
      if (c === 0 || c === 2) {
        cell.setBackgroundColor("#f1f5f9");
        cell.editAsText().setBold(true).setForegroundColor("#475569");
      }
    }
  }
}

function addWorkOrderItems(body, items, totalAmount) {
  addWorkOrderSectionTitle(body, "WORK SCHEDULE & ITEM MEASUREMENT SPECIFICATIONS");
  var rows = [["#", "Area of Specification", "Technical Specification / Details", "Measurement", "Unit", "Rate (₹)", "Amount (₹)"]];
  var areaTotal = 0;
  items.forEach(function(item, index) {
    var quantity = Number(item.measurement || 0);
    var rate = Number(item.rate || 0);
    var amount = quantity * rate;
    areaTotal += quantity;
    rows.push([
      String(index + 1),
      item.area || "",
      item.tech || item.technical || "",
      formatNumber(quantity),
      item.unit || "",
      formatNumber(rate),
      formatNumber(amount)
    ]);
  });
  rows.push(["", "", "TOTAL WORK VALUE", formatNumber(areaTotal), "", "Subtotal", formatRupees(totalAmount)]);
  var table = body.appendTable(rows);
  styleWorkOrderTable(table, true);
  table.setColumnWidth(0, 24).setColumnWidth(1, 100).setColumnWidth(2, 145)
    .setColumnWidth(3, 62).setColumnWidth(4, 48).setColumnWidth(5, 64).setColumnWidth(6, 80);
  var lastRow = table.getNumRows() - 1;
  for (var c = 0; c < table.getRow(lastRow).getNumCells(); c++) {
    table.getCell(lastRow, c).setBackgroundColor("#fff7e6").editAsText().setBold(true);
  }
}

function addWorkOrderMilestones(body, milestones, totalAmount) {
  addWorkOrderSectionTitle(body, "PAYMENT STAGES & MILESTONE TRIGGERS");
  var rows = [["Stage", "Description", "Scope / Area Type", "Percentage", "Payable Amount (₹)"]];
  var percentageTotal = 0;
  milestones.forEach(function(milestone, index) {
    var percentage = Number(milestone.pct || milestone.percentage || 0);
    percentageTotal += percentage;
    rows.push([
      String(index + 1),
      milestone.desc || milestone.description || "",
      milestone.type || milestone.scope || "TOTAL",
      formatNumber(percentage) + "%",
      formatRupees(Number(totalAmount || 0) * percentage / 100)
    ]);
  });
  rows.push(["", "TOTAL MILESTONE ALLOCATION", "", formatNumber(percentageTotal) + "%", formatRupees(totalAmount)]);
  var table = body.appendTable(rows);
  styleWorkOrderTable(table, true);
  table.setColumnWidth(0, 34).setColumnWidth(1, 178).setColumnWidth(2, 118)
    .setColumnWidth(3, 78).setColumnWidth(4, 115);
  var lastRow = table.getNumRows() - 1;
  for (var c = 0; c < table.getRow(lastRow).getNumCells(); c++) {
    table.getCell(lastRow, c).setBackgroundColor("#fff7e6").editAsText().setBold(true);
  }
}

function addWorkOrderTextSection(body, title, content) {
  var text = (content || "").toString().trim();
  if (!text) return;
  addWorkOrderSectionTitle(body, title);
  var lines = text.split(/\r?\n/);
  lines.forEach(function(line) {
    if (line.trim()) {
      var paragraph = body.appendParagraph(line.trim());
      paragraph.setSpacingAfter(3);
      paragraph.editAsText().setFontSize(8).setForegroundColor("#334155");
    }
  });
}

function addWorkOrderSectionTitle(body, title) {
  var paragraph = body.appendParagraph(title);
  paragraph.setSpacingBefore(9).setSpacingAfter(4);
  paragraph.setBackgroundColor("#1a2a3a");
  paragraph.editAsText().setBold(true).setFontSize(8).setForegroundColor("#ffffff");
}

function styleWorkOrderTable(table, hasHeader) {
  table.setBorderColor("#cbd5e1").setBorderWidth(0.5);
  for (var r = 0; r < table.getNumRows(); r++) {
    for (var c = 0; c < table.getRow(r).getNumCells(); c++) {
      var cell = table.getCell(r, c);
      cell.setPaddingTop(4).setPaddingBottom(4).setPaddingLeft(4).setPaddingRight(4);
      cell.editAsText().setFontSize(7);
      if (hasHeader && r === 0) {
        cell.setBackgroundColor("#1a2a3a");
        cell.editAsText().setBold(true).setForegroundColor("#ffffff");
      }
    }
  }
}

function addWorkOrderSignatures(body) {
  var signature = body.appendTable([[
    "Site Engineer / Prepared By\n\n\nSign & Stamp",
    "AGM (Projects)\n\n\nReviewed By",
    "COO / Director\n\n\nAuthorized Signatory",
    "Contractor\n\n\nAccepted By"
  ]]);
  signature.setBorderColor("#cbd5e1").setBorderWidth(0);
  for (var c = 0; c < signature.getRow(0).getNumCells(); c++) {
    var cell = signature.getCell(0, c);
    cell.setPaddingTop(18).setPaddingBottom(6).setPaddingLeft(4).setPaddingRight(4);
    cell.editAsText().setFontSize(7).setBold(true).setForegroundColor("#1a2a3a");
  }
}

function addWorkOrderPdfFooter(body) {
  var address = body.appendParagraph(CONFIG.COMPANY_ADDRESS);
  address.setAlignment(DocumentApp.HorizontalAlignment.CENTER);
  address.setSpacingBefore(8).setSpacingAfter(2);
  address.editAsText().setBold(true).setFontSize(7).setForegroundColor("#64748b");
  var note = body.appendParagraph("Generated by Oness Infra Enterprise ERP System. Valid with authorized organizational seals.");
  note.setAlignment(DocumentApp.HorizontalAlignment.CENTER);
  note.editAsText().setFontSize(6).setForegroundColor("#94a3b8");
}

function formatNumber(value) {
  var number = Number(value || 0);
  return isFinite(number) ? number.toLocaleString("en-IN", { maximumFractionDigits: 2 }) : "0";
}

function formatRupees(value) {
  return "₹" + formatNumber(value);
}

/**
 * Converts a sheet range with headers into an array of Javascript objects
 */
function sheetToObjects(sheet) {
  var lastRow = sheet.getLastRow();
  var lastCol = sheet.getLastColumn();
  if (lastRow < 2 || lastCol < 1) return [];

  var data = sheet.getRange(1, 1, lastRow, lastCol).getValues();
  var headers = data[0].map(function(h) { return h.toString().trim(); });
  var result = [];

  for (var i = 1; i < data.length; i++) {
    var row = data[i];
    var obj = {};
    var hasContent = false;
    for (var j = 0; j < headers.length; j++) {
      var cellVal = row[j];
      obj[headers[j]] = cellVal;
      if (cellVal !== "" && cellVal !== null && cellVal !== undefined) {
        hasContent = true;
      }
    }
    if (hasContent) {
      result.push(obj);
    }
  }
  return result;
}

/**
 * Extracts terms data into categorized arrays
 */
function extractTerms(sheet) {
  var rows = sheetToObjects(sheet);
  var specific = [];
  var payment = [];
  var basic = [];

  rows.forEach(function(row) {
    var s = row["Specific Terms & Conditions"] || row["Specific Terms"] || "";
    var p = row["Payment Terms & Conditions"] || row["Payment Terms"] || "";
    var b = row["Basic Terms & Conditions"] || row["Basic Terms"] || "";

    if (s && s.toString().trim()) specific.push(s.toString().trim());
    if (p && p.toString().trim()) payment.push(p.toString().trim());
    if (b && b.toString().trim()) basic.push(b.toString().trim());
  });

  return {
    specific: specific,
    payment: payment,
    basic: basic
  };
}

/**
 * Parses query strings if sent in raw payload format
 */
function parseQueryString(qs) {
  var params = {};
  var pairs = qs.split("&");
  for (var i = 0; i < pairs.length; i++) {
    var pair = pairs[i].split("=");
    var key = decodeURIComponent(pair[0].replace(/\+/g, " "));
    var val = decodeURIComponent((pair[1] || "").replace(/\+/g, " "));
    params[key] = val;
  }
  return params;
}

/**
 * Outputs a CORS-enabled JSON response to the client
 */
function createJsonResponse(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}