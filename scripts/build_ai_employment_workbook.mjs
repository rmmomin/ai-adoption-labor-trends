import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const src = path.join(root, 'outputs/ai_adoption_employment_comparison');
const out = path.resolve(process.argv[2] || src);
const build = path.join(out, '.build');
const dependencies = process.env.CODEX_WORKSPACE_NODE_MODULES || path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules');
await fs.mkdir(build, { recursive: true });
try { await fs.symlink(dependencies, path.join(build, 'node_modules')); }
catch (error) { if (error.code !== 'EEXIST') throw error; }
const require = createRequire(path.join(build, 'package.json'));
const { Workbook, SpreadsheetFile } = await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
const font = 'Helvetica Neue'; // Verified in /System/Library/Fonts/HelveticaNeue.ttc.
const blue = '#243B53', ink = '#203443';
const sourceName = { btos: 'Census BTOS', rps: 'RPS', ramp: 'Ramp' };
const splitName = { 4: 'Quartiles', 5: 'Quintiles', 2: 'Halves' };
const sourceUrl = {
  btos: 'https://www.census.gov/hfp/btos/downloads/Sector.xlsx',
  rps: 'https://www.genaiadoptiontracker.com/',
  ramp: 'https://datawrapper.dwcdn.net/wQR5S/23/dataset.csv',
};
const blsUrl = 'https://api.bls.gov/publicAPI/v2/timeseries/data/';
const key = r => `${r.source}/${r.groups}/${r.group}`;
const groupLabel = r => +r.groups === 2 ? (+r.group === 1 ? 'Lower half' : 'Higher half') : `Q${r.group}`;
const rowKey = r => `${key(r)}/${r.quarter}`;
const bool = x => x === 'True' || x === true;
const date = x => new Date(`${x}T00:00:00Z`);
function col(index) { let s = ''; for (++index; index; index = Math.floor((index - 1) / 26)) s = String.fromCharCode(65 + (index - 1) % 26) + s; return s; }
async function csv(name) {
  const temp = await Workbook.fromCSV(await fs.readFile(path.join(src, name), 'utf8'), { sheetName: 'Data' });
  const [headers, ...rows] = temp.worksheets.getItem('Data').getUsedRange().values;
  return rows.filter(r => r.some(v => v !== '' && v !== null)).map(r => Object.fromEntries(headers.map((h, i) => [h, r[i]])));
}
const q = await csv('all_chart_data.csv');
const m = await csv('monthly_chart_data.csv');
const groups = await csv('all_industry_memberships.csv');
const raw = await csv('industry_monthly_employment.csv');
const metadata = JSON.parse(await fs.readFile(path.join(src, 'source_metadata.json'), 'utf8'));
if (q.length !== 462 || m.length !== 1452 || groups.length !== 162 || raw.length !== 792) throw new Error('Unexpected data coverage');
const wb = Workbook.create();
const names = ['Quarterly indexes', 'Quarterly data', 'Monthly data', 'Industry groups', 'Industry payrolls', 'Notes and sources'];
const tabs = Object.fromEntries(names.map(name => [name, wb.worksheets.add(name)]));

function table(name, headers, rows, widths, subtitle) {
  const sh = tabs[name], n = rows.length, endCol = col(headers.length - 1), endRow = n + 5;
  const used = sh.getRange(`A1:${endCol}${endRow}`);
  used.format.font = { name: font, size: 10, color: ink };
  used.format.rowHeight = 24;
  used.format.verticalAlignment = 'center';
  sh.showGridLines = false;
  sh.getRange('A1').values = [[name]];
  sh.getRange('A1').format.font = { name: font, size: 16, bold: true, color: blue };
  sh.getRange(`A1:${endCol}1`).format.rowHeight = 30;
  sh.getRange(`A1:${endCol}1`).format.borders = { bottom: { style: 'thin', color: '#B5C5D0' } };
  sh.getRange('A2').values = [[subtitle]];
  sh.getRange('A2').format.font = { name: font, size: 10, italic: true, color: '#536A79' };
  sh.getRange(`A5:${endCol}${endRow}`).values = [headers, ...rows];
  const t = sh.tables.add(`A5:${endCol}${endRow}`, true, name.replaceAll(' ', '') + 'Table');
  t.showFilterButton = true;
  sh.getRange(`A5:${endCol}5`).format = {
    fill: blue, font: { name: font, size: 10, bold: true, color: '#FFFFFF' },
    horizontalAlignment: 'center', verticalAlignment: 'center', wrapText: true, rowHeight: 44,
    borders: { insideVertical: { style: 'thin', color: '#FFFFFF' } },
  };
  widths.forEach((w, i) => { sh.getRange(`${col(i)}1:${col(i)}${endRow}`).format.columnWidth = w; });
  sh.freezePanes.freezeRows(5);
  return sh;
}
function format(name, c, n, code) {
  tabs[name].getRange(`${c}6:${c}${n + 5}`).setNumberFormat(code);
  tabs[name].getRange(`${c}6:${c}${n + 5}`).format.horizontalAlignment = 'right';
}
function formulas(name, startCol, matrix) {
  tabs[name].getRangeByIndexes(5, startCol, matrix.length, matrix[0].length).formulas = matrix;
}

const qRows = q.map(r => [sourceName[r.source], splitName[r.groups], groupLabel(r), r.quarter,
  +r.employment_thousands, null, null, null, +r.industry_count, +r.observed_months, bool(r.preliminary), r.ranking_date, sourceUrl[r.source]]);
const qSheet = table('Quarterly data', ['Source', 'Grouping', 'AI group', 'Quarter', 'Payroll jobs (thousands)', '2023 Q1 jobs (thousands)', 'Employment index', 'Growth since 2023 Q1', 'Industries', 'Observed months', 'Preliminary', 'Adoption ranking date', 'Adoption source URL'], qRows,
  [18, 16, 16, 13, 21, 23, 18, 22, 12, 14, 14, 26, 64], 'Complete-quarter averages, 2023 Q1 = 100. Payroll levels: BLS CES. Source definitions are on Notes and sources.');
const baseRows = new Map(q.flatMap((r, i) => r.quarter === '2023Q1' ? [[key(r), i + 6]] : []));
const qLookup = new Map(q.map((r, i) => [rowKey(r), i + 6]));
formulas('Quarterly data', 5, q.map((r, i) => [`=$E$${baseRows.get(key(r))}`, `=100*E${i + 6}/F${i + 6}`, `=G${i + 6}/100-1`]));
for (const c of ['E', 'F']) format('Quarterly data', c, q.length, '#,##0.0');
format('Quarterly data', 'G', q.length, '0.00');
format('Quarterly data', 'H', q.length, '0.00%');
for (const c of ['I', 'J']) format('Quarterly data', c, q.length, '0');

const quarters = [...new Set(q.map(r => r.quarter))].sort();
const series = q.filter(r => r.quarter === '2023Q1');
const indexRows = series.map(r => [sourceName[r.source], splitName[r.groups], groupLabel(r), ...quarters.map(() => null)]);
table('Quarterly indexes', ['Source', 'Grouping', 'AI group', ...quarters], indexRows,
  [18, 16, 16, ...quarters.map(() => 13)], 'All nine charts, 2023 Q1 = 100. Each row is one series. Group 1 has the lowest adoption.');
formulas('Quarterly indexes', 3, series.map(r => quarters.map(quarter => `='Quarterly data'!G${qLookup.get(`${key(r)}/${quarter}`)}`)));
tabs['Quarterly indexes'].getRange(`D6:Q${series.length + 5}`).setNumberFormat('0.00');
tabs['Quarterly indexes'].getRange(`D6:Q${series.length + 5}`).format.horizontalAlignment = 'right';
tabs['Quarterly indexes'].freezePanes.freezeColumns(3);

const mRows = m.map(r => [sourceName[r.source], splitName[r.groups], groupLabel(r), date(r.date), r.quarter,
  +r.employment_thousands, null, null, null, +r.industry_count, bool(r.preliminary), r.ranking_date, sourceUrl[r.source]]);
table('Monthly data', ['Source', 'Grouping', 'AI group', 'Month', 'Quarter', 'Payroll jobs (thousands)', '2023 Q1 jobs (thousands)', 'Employment index', 'Growth vs 2023 Q1 average', 'Industries', 'Preliminary', 'Adoption ranking date', 'Adoption source URL'], mRows,
  [18, 16, 16, 15, 13, 22, 23, 18, 24, 12, 14, 26, 64], 'January 2023–August 2026. Monthly indexes use the 2023 Q1 average as their denominator.');
formulas('Monthly data', 6, m.map((r, i) => [`='Quarterly data'!$E$${baseRows.get(key(r))}`, `=100*F${i + 6}/G${i + 6}`, `=H${i + 6}/100-1`]));
format('Monthly data', 'D', m.length, 'mmm yyyy');
for (const c of ['F', 'G']) format('Monthly data', c, m.length, '#,##0.0');
format('Monthly data', 'H', m.length, '0.00');
format('Monthly data', 'I', m.length, '0.00%');
format('Monthly data', 'J', m.length, '0');

const gRows = groups.map(r => [sourceName[r.source], splitName[r.groups], groupLabel(r), String(r.naics), r.industry,
  +r.ai_adoption_pct / 100, +r.adoption_rank, r.series_id, +r.base_employment_thousands, null,
  r.ranking_date, r.ai_standard_error_pp === '' || r.ai_standard_error_pp === null ? null : +r.ai_standard_error_pp,
  r.source_url || sourceUrl[r.source]]);
table('Industry groups', ['Source', 'Grouping', 'AI group', 'NAICS', 'Industry', 'AI adoption rate', 'Adoption rank', 'CES series ID', '2023 Q1 jobs (thousands)', 'Base employment weight', 'Adoption ranking date', 'Adoption SE (pp)', 'Adoption source URL'], gRows,
  [18, 16, 16, 13, 47, 18, 15, 24, 24, 23, 26, 18, 64], 'Fixed assignments among 18 industries. Weights are each industry’s share of its group’s 2023 Q1 payroll jobs.');
tabs['Industry groups'].getRange(`E6:E${groups.length + 5}`).format.wrapText = true;
tabs['Industry groups'].getRange(`A6:M${groups.length + 5}`).format.rowHeight = 38;
formulas('Industry groups', 9, groups.map((r, i) => [`=I${i + 6}/SUMIFS($I$6:$I$167,$A$6:$A$167,A${i + 6},$B$6:$B$167,B${i + 6},$C$6:$C$167,C${i + 6})`]));
format('Industry groups', 'F', groups.length, '0.00%');
format('Industry groups', 'G', groups.length, '0');
format('Industry groups', 'I', groups.length, '#,##0.0');
format('Industry groups', 'J', groups.length, '0.00%');
format('Industry groups', 'L', groups.length, '0.00');

const rawRows = raw.map(r => [date(r.date), String(r.naics), r.industry, r.series_id, +r.employment_thousands, bool(r.preliminary), r.quarter, blsUrl]);
table('Industry payrolls', ['Month', 'NAICS', 'Industry', 'CES series ID', 'Payroll jobs (thousands)', 'Preliminary', 'Quarter', 'Employment source URL'], rawRows,
  [15, 13, 48, 24, 24, 14, 13, 65], 'BLS CES seasonally adjusted private payroll jobs, January 2023–August 2026. No imputed observations.');
tabs['Industry payrolls'].getRange(`C6:C${raw.length + 5}`).format.wrapText = true;
tabs['Industry payrolls'].getRange(`A6:H${raw.length + 5}`).format.rowHeight = 38;
format('Industry payrolls', 'A', raw.length, 'mmm yyyy');
format('Industry payrolls', 'E', raw.length, '#,##0.0');

const notes = [
  ['Coverage', 'Quarterly chart data: 2023 Q1–2026 Q2, 14 quarters. Monthly data: January 2023–August 2026, 44 months. There are 33 series across nine source/grouping combinations.', ''],
  ['Workbook contents', 'Quarterly indexes: one row per series. Quarterly data and Monthly data: filterable detailed observations. Industry groups: assignments, adoption and weights. Industry payrolls: underlying CES observations.', ''],
  ['Base and units', 'Employment indexes equal 100 in 2023 Q1. Payroll employment is measured in thousands of jobs. Growth and adoption cells store numeric fractions with percentage formats. Adoption standard errors are in percentage points.', ''],
  ['Grouping', 'Rank 18 industries by each source’s adoption rate and break ties by NAICS. Quartiles contain 5/4/4/5 industries, quintiles 4/3/4/3/4, and halves 9/9. Membership remains fixed.', ''],
  ['Quarterly calculation', 'Sum monthly payroll employment within each group, then average all three months of the quarter. Divide each quarterly average by its 2023 Q1 average and multiply by 100.', ''],
  ['Monthly calculation', 'Divide each monthly group payroll total by the group’s 2023 Q1 quarterly average and multiply by 100. The January–March 2023 monthly indexes average 100. Individual monthly values need not equal 100.', ''],
  ['Incomplete quarter', 'July and August 2026 are included in the monthly tab. 2026 Q3 is excluded from the quarterly tabs because September is unavailable. No employment observations are imputed or forecast.', ''],
  ['Formula scope', 'Group payroll levels and fixed memberships are imported from the chart datasets. Workbook formulas calculate baseline references, indexes, growth and weights. Editing raw industry observations does not rerun the external aggregation or adoption ranking.', ''],
  ['Employment coverage', 'Same 18 broad private nonfarm industries in all comparisons. Agriculture/forestry/fishing, logging, government and self-employment are excluded. Education and healthcare use private payroll employment.', 'https://www.bls.gov/ces/'],
  ['Preliminary flag', 'TRUE means at least one underlying CES employment observation is preliminary. FALSE means the archived source did not flag the observation as preliminary.', ''],
  ['Census BTOS', 'Fixed period 202618, reference August 10–23, 2026, published September 10, 2026. Share of businesses using AI in any business function during the preceding two weeks.', sourceUrl.btos],
  ['RPS', 'Bick–Blandin–Deming Real-Time Population Survey via St. Louis Fed/FRED. May 2026 wave, represented by the 2026 Q2 timestamp. Share of employed adults aged 18–64 using generative AI for their job. This is not a Chicago Fed survey.', sourceUrl.rps],
  ['RPS example series', 'Each RPS industry’s FRED table URL is included in Industry groups. Cite Bick, Blandin and Deming, The Rapid Adoption of Generative AI, Management Science (2026).', 'https://fred.stlouisfed.org/series/RPSGENAIUSAGESHAREIND5'],
  ['Ramp', 'Fixed April 2026 complete 18-sector public download, version 23. Paid AI adoption observed among businesses using Ramp. This preserves common sector coverage across sources.', sourceUrl.ramp],
  ['Ramp methodology', 'Ramp measures paid AI adoption among its business customers. Free use or payments outside Ramp may be absent.', 'https://ramp.com/data/ai-index'],
  ['Employment source', 'Archived BLS CES all-employees seasonally adjusted series. The sector-to-series mapping appears in Industry groups and Industry payrolls.', blsUrl],
  ['Interpretation', 'The sources differ in adoption definition, population and ranking date. Payrolls cover whole industries, not only adopting firms. Recent rankings are applied retrospectively. These descriptive comparisons do not identify a causal effect of AI.', ''],
  ['Adoption uncertainty', 'BTOS standard errors are included when supplied. Blank RPS and Ramp standard-error cells mean unavailable, not zero. No confidence bands were inferred.', ''],
  ['Source vintage', `Chart dataset built ${metadata.built_at_utc.slice(0, 10)} from archived inputs. Values may differ from subsequently revised releases.`, ''],
];
table('Notes and sources', ['Topic', 'Definition or method', 'Source URL'], notes, [26, 102, 74], 'Definitions, coverage and sources for the payroll employment chart data.');
tabs['Notes and sources'].getRange(`A6:C${notes.length + 5}`).format.wrapText = true;
tabs['Notes and sources'].getRange(`A6:C${notes.length + 5}`).format.rowHeight = 64;
tabs['Notes and sources'].getRange(`A6:C${notes.length + 5}`).format.verticalAlignment = 'top';

const audits = [];
function reconcile(name, range, expected, tolerance) {
  const actual = tabs[name].getRange(range).values.flat();
  if (actual.length !== expected.length) throw new Error(`Length mismatch: ${name}`);
  const maxError = Math.max(...actual.map((v, i) => typeof v === 'number' && Number.isFinite(v) ? Math.abs(v - expected[i]) : Infinity));
  if (maxError > tolerance) throw new Error(`${name} mismatch ${maxError}`);
  audits.push({ sheet: name, range, values: actual.length, maxError });
}
reconcile('Quarterly data', 'G6:G467', q.map(r => +r.employment_index), 1e-8);
reconcile('Monthly data', 'H6:H1457', m.map(r => +r.employment_index), 1e-8);
reconcile('Industry groups', 'J6:J167', groups.map(r => +r.base_employment_weight), 1e-10);
const qValues = new Map(q.map(r => [rowKey(r), +r.employment_index]));
reconcile('Quarterly indexes', 'D6:Q38', series.flatMap(r => quarters.map(quarter => qValues.get(`${key(r)}/${quarter}`))), 1e-8);
const inspection = await wb.inspect({ kind: 'table', range: 'Quarterly indexes!A5:H9', include: 'values,formulas', tableMaxRows: 5, tableMaxCols: 8, maxChars: 3500 });
await fs.writeFile(path.join(out, '.build/inspection.ndjson'), inspection.ndjson);
const errors = await wb.inspect({ kind: 'match', searchTerm: '#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!', options: { useRegex: true, maxResults: 30 }, summary: 'Formula error scan', maxChars: 2000 });
console.log(errors.ndjson);
await fs.writeFile(path.join(out, '.build/validation.json'), JSON.stringify(audits, null, 2));
for (const [name, range] of [
  ['Quarterly indexes', 'A1:J14'], ['Quarterly data', 'A1:M12'], ['Monthly data', 'A1:M12'],
  ['Industry groups', 'A1:M12'], ['Industry payrolls', 'A1:H12'], ['Notes and sources', 'A1:C24'],
]) {
  const preview = await wb.render({ sheetName: name, range, scale: 1, format: 'png' });
  await fs.writeFile(path.join(out, `.build/${name.replaceAll(' ', '_')}.png`), new Uint8Array(await preview.arrayBuffer()));
}
const output = await SpreadsheetFile.exportXlsx(wb);
await output.save(path.join(out, 'ai_adoption_payroll_employment.xlsx'));
console.log(JSON.stringify({ workbook: path.join(out, 'ai_adoption_payroll_employment.xlsx'), sheets: names, audits }, null, 2));
