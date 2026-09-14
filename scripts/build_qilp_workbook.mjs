// Render the research extension with the bundled Codex spreadsheet library.
import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

const out = path.resolve(process.argv[2] || 'outputs/qilp_update_01a0a142');
const deps = process.env.CODEX_WORKSPACE_NODE_MODULES || '/Users/rayhanmomin/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
await fs.mkdir(path.join(out, '.build'), { recursive: true });
try { await fs.symlink(deps, path.join(out, '.build/node_modules')); }
catch (error) { if (error.code !== 'EEXIST') throw error; }
const require = createRequire(path.join(out, '.build/entry.cjs'));
const { Workbook, SpreadsheetFile } = await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
const d = JSON.parse(await fs.readFile(path.join(out, 'workbook_data.json'), 'utf8'));
const wb = Workbook.create();
const names = ['Read Me', 'Latest', ...Object.keys(d.sheets), 'Coverage', 'CES Mapping', 'Extension Inputs'];
const tabs = Object.fromEntries(names.map(name => [name, wb.worksheets.add(name)]));
const font = 'Helvetica Neue'; // Verified in /System/Library/Fonts/HelveticaNeue.ttc.
const navy = '#243B53';
function col(n) { let s = ''; for (++n; n; n = Math.floor((n-1)/26)) s = String.fromCharCode(65+(n-1)%26)+s; return s; }
function table(sheet, matrix, widths, height = 32) {
  const end = `${col(matrix[0].length-1)}${matrix.length}`;
  sheet.getRange(`A1:${end}`).values = matrix;
  sheet.getRange(`A1:${end}`).format.font = { name: font, size: 10, color: '#172B4D' };
  sheet.getRange(`A1:${end}`).format.rowHeight = height;
  sheet.getRange(`A1:${end}`).format.verticalAlignment = 'center';
  sheet.getRange(`A1:${end}`).format.wrapText = true;
  sheet.getRange(`A1:${col(matrix[0].length-1)}1`).format = {
    fill: navy, font: { name: font, size: 10, bold: true, color: '#FFFFFF' },
    wrapText: true, horizontalAlignment: 'center', rowHeight: 38,
  };
  widths.forEach((w, i) => { sheet.getRange(`${col(i)}1:${col(i)}${matrix.length}`).format.columnWidth = w; });
  sheet.showGridLines = false;
  sheet.freezePanes.freezeRows(1);
  return end;
}
const dates = d.quarters.map(q => new Date(Date.UTC(Number(q.slice(0,4)), (Number(q.slice(-1))-1)*3, 1)));
const baseIndex = d.quarters.indexOf(d.base);
const lastColumn = col(3+d.quarters.length-1);
const anchorColumn = col(3+baseIndex);
for (const [name, data] of Object.entries(d.sheets)) {
  const matrix = [['industry', 'level', 'gdp_line', ...dates], ...d.industries.map((i, j) => [i.industry, i.level, i.gdp_line, ...data[j]])];
  const sheet = tabs[name];
  table(sheet, matrix, [62, 8, 11, ...dates.map(() => name === 'Nominal Output' ? 20 : name === 'Total Hours' ? 18 : 14)], 34);
  sheet.getRange(`D1:${lastColumn}1`).setNumberFormat('mmm yyyy');
  sheet.getRange(`D2:${lastColumn}${matrix.length}`).setNumberFormat(['Total Hours','Nominal Output'].includes(name) ? '#,##0' : name === 'Employment' ? '#,##0' : '0.00');
  sheet.getRange(`D2:${lastColumn}${matrix.length}`).format.horizontalAlignment = 'right';
  sheet.getRange(`${col(4+baseIndex)}1:${lastColumn}1`).format.fill = '#835C24';
  sheet.freezePanes.freezeColumns(3);
}
const input = tabs['Extension Inputs'];
table(input, [['gdp_line','industry','quarter','Output factor','Hours factor','Employment factor','Productivity factor','Nominal output factor'], ...d.inputs.map(x => [x.gdp_line,x.industry,x.quarter,x.output_factor,x.hours_factor,x.employment_factor,x.productivity_factor,x.nominal_factor])], [10,62,12,15,15,18,18,19], 34);
input.getRange(`D2:H${d.inputs.length+1}`).setNumberFormat('0.000000');
const industryRow = new Map(d.industries.map((x,i) => [x.gdp_line,i+2]));
const inputRow = new Map(d.inputs.map((x,i) => [`${x.gdp_line}:${x.quarter}`,i+2]));
for (const [i, x] of d.inputs.entries()) {
  const ir = i+2, r = industryRow.get(x.gdp_line), c = col(3+d.quarters.indexOf(x.quarter));
  if (x.gdp_line !== 88) input.getRange(`G${ir}`).formulas = [[`=D${ir}/E${ir}`]];
  tabs['Labor Productivity'].getRange(`${c}${r}`).formulas = [[`=$${anchorColumn}${r}*'Extension Inputs'!G${ir}`]];
  if (x.gdp_line === 88) continue;
  for (const [sheet, factor] of [['Total Hours','E'],['Employment','F'],['Nominal Output','H']]) {
    tabs[sheet].getRange(`${c}${r}`).formulas = [[`=$${anchorColumn}${r}*'Extension Inputs'!${factor}${ir}`]];
  }
  const prev = d.quarters[d.quarters.indexOf(x.quarter)-1];
  const prevRow = inputRow.get(`${x.gdp_line}:${prev}`);
  for (const [sheet, factor] of [['Real Output Growth','D'],['Hours Growth','E']]) {
    const denom = prevRow ? `'Extension Inputs'!${factor}${prevRow}` : '1';
    tabs[sheet].getRange(`${c}${r}`).formulas = [[`=400*LN('Extension Inputs'!${factor}${ir}/${denom})`]];
  }
}
const latestRows = d.coverage.filter(x => x.status !== 'not_extended');
const latest = tabs.Latest;
table(latest, [['Industry',`${d.base} index`,`${d.latest} index`,'Change since anchor (%)','Overlap MAE (pp)','Estimate type'], ...latestRows.map(x => [x.industry,null,null,null,x.mae_pp,x.status==='linked_bls_benchmark'?'Linked BLS benchmark':'Research extension'])], [62,16,16,20,19,24], 34);
for (const [i, x] of latestRows.entries()) {
  const r=i+2, sr=industryRow.get(x.gdp_line);
  latest.getRange(`B${r}:D${r}`).formulas = [[`='Labor Productivity'!${anchorColumn}${sr}`,`='Labor Productivity'!${lastColumn}${sr}`,`=100*(C${r}/B${r}-1)`]];
}
latest.getRange(`B2:E${latestRows.length+1}`).setNumberFormat('0.00');
latest.getRange(`F2:F${latestRows.length+1}`).format.horizontalAlignment = 'center';
const coverage = tabs.Coverage;
table(coverage, [['Industry','gdp_line','Treatment','Overlap MAE (pp)','Max overlap error (pp)','Method note'], ...d.coverage.map(x => [x.industry,x.gdp_line,x.status,x.mae_pp,x.max_abs_error_pp,x.method_note])], [62,11,26,18,22,90], 52);
coverage.getRange(`D2:E${d.coverage.length+1}`).setNumberFormat('0.00');
coverage.getRange(`B2:B${d.coverage.length+1}`).format.horizontalAlignment = 'center';
const mapping = tabs['CES Mapping'];
table(mapping, [['gdp_line','Industry','Coefficient','Employment series','Weekly-hours series','AWH proxy','Mapping note','Source URL'], ...d.mapping.map(x => [x.gdp_line,x.industry,x.coefficient,x.employment_series,x.awh_series,x.awh_proxy,x.notes,x.source_url])], [11,62,12,23,23,14,85,65], 52);
mapping.getRange(`A2:A${d.mapping.length+1}`).format.horizontalAlignment = 'center';
mapping.getRange(`C2:C${d.mapping.length+1}`).format.horizontalAlignment = 'center';
input.getRange(`A2:A${d.inputs.length+1}`).format.horizontalAlignment = 'center';
const checks = d.metadata.checks;
const notes = [
 ['Quarterly industry labor productivity',null],
 [`Research extension through ${d.latest}`,null],
 ['Item','Details'],
 ['Status','Independent research estimates. Not an official Chicago Fed update or exact replication.'],
 ['Coverage',`${checks.research_rows_extended} research rows and one linked BLS benchmark. All 89 original rows retained; five unextended rows are identified in Coverage.`],
 ['Published history',`Six measure sheets preserve the published QILP history through ${d.base}. The original file remains separately archived.`],
 ['New quarters',checks.new_quarters.join(', ')],
 ['Productivity formula','Published anchor index × current BEA quantity-index ratio ÷ current CES payroll-hours ratio. Index scale follows published QILP (2017 = 100).'],
 ['Hours assumption','Combined payroll, self-employed and unpaid-family hours are assumed to grow at the mapped payroll-hours rate. CPS microdata and X-13 are not re-estimated.'],
 ['Quarterly payroll hours','Mean of three monthly employment × all-employee average-weekly-hours products. Inputs are seasonally adjusted. Component hours are added or subtracted first.'],
 ['Growth units','Annualized log percent: 400 × log(current quarter / prior quarter). These are not exact compounded annual percentage changes.'],
 ['Nominal Output','New values are linked to the old published nominal anchor using current BEA growth. They are not current-vintage BEA dollar levels. Current BEA levels are in the companion CSV.'],
 ['Aggregation','Most groups use BEA quantity indexes and mapped CES groups. Nonfarm private uses 18-sector Tornqvist output and summed sector-hours growth, rescaled to the published aggregate anchor. Parent/child rows must not be summed.'],
 ['Benchmark','Private Nonfarm Business links BLS PRS85006093 productivity growth to its published anchor. Its other measures are not extended.'],
 ['Missing extensions','Agriculture, forestry/fishing and the all-private aggregate including agriculture: four rows. Funds/trusts: negative published productivity anchor. No extrapolation for these five rows.'],
 ['Overlap validation',`Three-quarter change MAE: ${checks.overlap_three_quarter_mae_pp.toFixed(2)} percentage points across mapped rows; ${checks.broad_sector_overlap_three_quarter_mae_pp.toFixed(2)} points for 18 broad sectors.`],
 ['Interpreting overlap','Current-vintage historical comparisons include revisions and method differences. They are not real-time forecast tests or confidence intervals. Fine industry rankings can be unreliable.'],
 ['Substitutions','CES Mapping records hours proxies, component omissions and industry-classification mismatches. All new industry estimates also depend on the self-employment assumption.'],
 ['Validation','Published history unchanged; complete monthly coverage; positive extended anchors/hours; BEA names matched; productivity growth identity checked.'],
 ['Source vintage (UTC)',new Date(d.metadata.retrieved_at_utc)],
 ['Next BEA industry release','September 30, 2026 is the scheduled release for 2026 Q2, as checked September 14, 2026.'],
 ['Paper',d.metadata.urls['article.html']],
 ['Published QILP',d.metadata.urls['qilp_published.xlsx']],
 ['QILP release notes',d.metadata.urls['qilp-release-notes.pdf']],
 ['BEA value added',d.metadata.urls['ValueAdded.xlsx']],
 ['BLS API','https://api.bls.gov/publicAPI/v2/timeseries/data/'],
 ['CES definitions','https://www.bls.gov/ces/data/'],
 ['BEA schedule','https://www.bea.gov/data/gdp/gdp-industry'],
];
const readme = tabs['Read Me'];
table(readme, notes, [34,112], 47);
readme.getRange('A1:B2').format.fill = '#FFFFFF';
readme.getRange('A1:B2').format.font = {name:font,size:14,bold:true,color:navy};
readme.getRange('A1:B2').format.horizontalAlignment = 'left';
readme.getRange('A1:B2').format.rowHeight = 44;
readme.getRange('A3:B3').format = {fill:navy,font:{name:font,size:10,bold:true,color:'#FFFFFF'},rowHeight:28};
readme.getRange('B20').setNumberFormat('yyyy-mm-dd hh:mm');
readme.getRange('B20').format.horizontalAlignment = 'left';
readme.freezePanes.unfreeze();
// Source data and independently calculated Python results must agree with workbook formulas.
let maxRelativeError = 0;
for (const [name, values] of Object.entries(d.sheets)) {
  for (const x of d.inputs) {
    if (name !== 'Labor Productivity' && x.gdp_line === 88) continue;
    const i = industryRow.get(x.gdp_line)-2, j=d.quarters.indexOf(x.quarter);
    const actual = tabs[name].getRange(`${col(3+j)}${i+2}`).values[0][0];
    const expected = values[i][j];
    if (typeof actual !== 'number' || !Number.isFinite(actual)) throw new Error(`Invalid formula ${name} ${x.gdp_line} ${x.quarter}: ${actual}`);
    maxRelativeError = Math.max(maxRelativeError,Math.abs(actual-expected)/Math.max(1,Math.abs(expected)));
  }
}
if (maxRelativeError > 1e-9) throw new Error(`Workbook formula discrepancy: ${maxRelativeError}`);
console.log((await wb.inspect({kind:'table',range:'Latest!A1:F7',include:'values,formulas',tableMaxRows:7,tableMaxCols:6,maxChars:2000})).ndjson);
const errors = await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:30},summary:'Formula error scan'});
console.log(errors.ndjson);
await fs.mkdir(path.join(out,'.previews'),{recursive:true});
const renderOnly = process.env.QILP_RENDER_SHEETS?.split('|');
for (const name of names.filter(n => !renderOnly || renderOnly.includes(n))) {
  const range = name==='Read Me'?'A1:B17':name==='Coverage'?'A1:F8':name==='CES Mapping'?'A1:F7':name==='Extension Inputs'?'A1:H8':name==='Latest'?'A1:F9':'A1:H12';
  const preview = await wb.render({sheetName:name,range,scale:1,format:'png'});
  await fs.writeFile(path.join(out,'.previews',name.replaceAll(' ','_')+'.png'),new Uint8Array(await preview.arrayBuffer()));
}
for (const [name, range, filename] of [
  ['Read Me','A18:B28','Sources'],
  ['Labor Productivity',`${anchorColumn}1:${lastColumn}12`,'Latest_Quarter_Columns'],
]) {
  const preview = await wb.render({sheetName:name,range,scale:1,format:'png'});
  await fs.writeFile(path.join(out,'.previews',filename+'.png'),new Uint8Array(await preview.arrayBuffer()));
}
const result = await SpreadsheetFile.exportXlsx(wb);
await result.save(path.join(out,'qilp_research_extension.xlsx'));
await fs.writeFile(path.join(out,'workbook_validation.json'),JSON.stringify({formula_relative_error:maxRelativeError,formula_error_scan:errors.ndjson,rendered_sheets:names,font_family:font},null,2));
console.log(`Saved ${path.join(out,'qilp_research_extension.xlsx')}`);
