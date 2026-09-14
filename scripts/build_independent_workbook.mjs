import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const out = path.resolve(process.env.PRODUCTIVITY_OUT_DIR || path.join(root, 'outputs/independent_productivity_01a0a142'));
const dependencies = process.env.CODEX_WORKSPACE_NODE_MODULES || '/Users/rayhanmomin/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
const build = path.join(out, '.build');
await fs.mkdir(build, {recursive:true});
try { await fs.symlink(dependencies, path.join(build,'node_modules'), 'dir'); } catch(e) { if(e.code!=='EEXIST') throw e; }
const require = createRequire(path.join(build,'package.json'));
const {Workbook, SpreadsheetFile, FileBlob} = await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
const input = JSON.parse(await fs.readFile(path.join(out,'workbook_data.json'),'utf8'));

// Narrow follow-up edit: retain the existing workbook and change October's
// treatment cells only. The normal build below reproduces the same formulas.
if(process.argv.includes('--edit-october')){
  const workbookPath=path.join(out,'independent_quarterly_productivity.xlsx');
  const workbook=await SpreadsheetFile.importXlsx(await FileBlob.load(workbookPath));
  const guide=workbook.worksheets.getItem('Guide');
  const overview=input.sheets.find(s=>s.name==='Guide');
  const guideIndex=overview.rows.findIndex(r=>r[0]==='October 2025');
  guide.getRange(`B${guideIndex+2}`).values=[[overview.rows[guideIndex][1]]];
  const monthlySpec=input.sheets.find(s=>s.name==='Monthly inputs');
  const monthly=workbook.worksheets.getItem('Monthly inputs');
  const edited=[];
  for(let i=0;i<monthlySpec.rows.length;i++){
    const row=monthlySpec.rows[i];
    if(row[2]!=='2025-10-01')continue;
    const excelRow=i+2;
    if(monthlySpec.rows[i-1][0]!==row[0]||monthlySpec.rows[i+1][0]!==row[0])throw new Error('Industry interpolation boundary');
    monthly.getRange(`F${excelRow}:G${excelRow}`).formulas=[[
      `=(F${excelRow-1}+F${excelRow+1})/2`,`=(G${excelRow-1}+G${excelRow+1})/2`]];
    monthly.getRange(`K${excelRow}:L${excelRow}`).values=[[0,0]];
    const actual=monthly.getRange(`F${excelRow}:G${excelRow}`).values[0];
    if(actual.some((v,j)=>Math.abs(v-row[j+5])>1e-6))throw new Error('October formula mismatch');
    edited.push(excelRow);
  }
  if(edited.length!==18)throw new Error('Expected 18 October industry rows');
  for(const [sheetName,range,label] of [
    ['Guide','A5:B9','Guide'],
    ['Monthly inputs',`C${edited[0]-1}:M${edited[0]+1}`,'October_2025']]){
    const preview=await workbook.render({sheetName,range,scale:1.3,format:'png'});
    await fs.writeFile(path.join(out,`preview_${label}.png`),new Uint8Array(await preview.arrayBuffer()));
  }
  const errors=await workbook.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:30},summary:'October edit formula scan',maxChars:3000});
  await fs.writeFile(path.join(out,'workbook_formula_scan.ndjson'),errors.ndjson);
  console.log(errors.ndjson);
  await fs.writeFile(path.join(out,'workbook_october_edit_validation.json'),JSON.stringify({industries:edited.length,editedRows:edited,midpointFormulasMatchPython:true},null,2));
  const file=await SpreadsheetFile.exportXlsx(workbook);
  await file.save(workbookPath);
  console.log('Updated October treatment in independent_quarterly_productivity.xlsx');
  process.exit(0);
}
const workbook=Workbook.create();
const audits=[];
for(const spec of input.sheets){
  const sheet=workbook.worksheets.add(spec.name);
  const height=spec.rows.length+1, width=spec.headers.length;
  const range=sheet.getRangeByIndexes(0,0,height,width);
  range.values=[spec.headers,...spec.rows];
  range.format.font={name:'Arial',size:10,color:'#263640'};
  range.format.rowHeight=18;
  range.format.columnWidth=21;
  range.format.verticalAlignment='center';
  sheet.showGridLines=false;
  sheet.getRangeByIndexes(0,0,1,width).format={fill:'#263E4A',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},wrapText:true,rowHeight:42};
  if(spec.name==='Guide'){
    sheet.getRange('A:A').format.columnWidth=29;
    sheet.getRange('B:B').format.columnWidth=108;
    sheet.getRangeByIndexes(1,0,height-1,2).format.wrapText=true;
    sheet.getRangeByIndexes(1,0,height-1,2).format.rowHeight=48;
  }else{
    sheet.freezePanes.freezeRows(1);
    sheet.tables.add(`A1:${String.fromCharCode(64+width)}${height}`,true,spec.name.replaceAll(' ','')+'Table');
    sheet.getRangeByIndexes(1,0,height-1,width).setNumberFormat('#,##0.00');
    sheet.getRangeByIndexes(1,0,height-1,1).setNumberFormat('@');
    if(['Productivity','Monthly inputs','Hours alternatives','Detailed payroll'].includes(spec.name)){
      sheet.getRange('A:A').format.columnWidth=12;
      sheet.getRange('B:B').format.columnWidth=48;
      sheet.getRange('C:C').format.columnWidth=15;
      sheet.getRangeByIndexes(1,1,height-1,1).format.wrapText=true;
      sheet.getRangeByIndexes(1,0,height-1,width).format.rowHeight=30;
    }
  }
  if(spec.name==='Productivity'){
    const formulas=spec.rows.map((r,i)=>[`=100*(D${i+2}/E${i+2})/(G${i+2}/H${i+2})`]);
    sheet.getRangeByIndexes(1,8,spec.rows.length,1).formulas=formulas;
    const growth=spec.rows.map((r,i)=>[i>0&&r[0]===spec.rows[i-1][0]?`=(I${i+2}/I${i+1})^4-1`:'']);
    sheet.getRangeByIndexes(1,9,spec.rows.length,1).formulas=growth;
    sheet.getRangeByIndexes(1,9,spec.rows.length,1).setNumberFormat('0.00%');
    sheet.getRange('K:K').setNumberFormat('0');
    sheet.getRange('L:L').format.columnWidth=82;
    const actual=sheet.getRangeByIndexes(1,8,spec.rows.length,1).values;
    const maxError=Math.max(...actual.map((r,i)=>Math.abs(r[0]-spec.rows[i][8])));
    if(maxError>1e-7)throw new Error(`Productivity formulas differ by ${maxError}`);
    audits.push({check:'Productivity formulas vs independent Python',maxError});
  }
  if(spec.name==='AI group data'){
    sheet.getRange('B:B').format.columnWidth=29;
    sheet.getRangeByIndexes(1,2,spec.rows.length,2).setNumberFormat('0');
    sheet.getRangeByIndexes(1,4,spec.rows.length,1).formulas=spec.rows.map((r,i)=>[`=100*F${i+2}/G${i+2}`]);
    sheet.getRangeByIndexes(1,7,spec.rows.length,1).setNumberFormat('0.00%');
  }
  if(spec.name==='CES mapping'){
    sheet.getRangeByIndexes(1,1,spec.rows.length,2).setNumberFormat('@');
    sheet.getRangeByIndexes(1,3,spec.rows.length,1).setNumberFormat('0');
    sheet.getRange('E:F').format.columnWidth=82;
    sheet.getRange('G:G').format.columnWidth=106;
  }
  if(spec.name==='Monthly inputs'){
    sheet.getRangeByIndexes(1,3,spec.rows.length,1).setNumberFormat('#,##0');
    sheet.getRangeByIndexes(1,5,spec.rows.length,2).setNumberFormat('#,##0');
    sheet.getRangeByIndexes(1,10,spec.rows.length,2).setNumberFormat('#,##0');
    for(let i=0;i<spec.rows.length;i++){
      if(spec.rows[i][2]!=='2025-10-01')continue;
      const r=i+2;
      sheet.getRange(`F${r}:G${r}`).formulas=[[`=(F${r-1}+F${r+1})/2`,`=(G${r-1}+G${r+1})/2`]];
    }
  }
  if(spec.name==='Detailed payroll')sheet.getRange('I:I').format.columnWidth=75;
  if(spec.name==='AI halves'){
    sheet.getRange('B:C').format.columnWidth=24;
    const chart=sheet.charts.add('line',sheet.getRangeByIndexes(0,0,height,width));
    chart.title='Productivity by RPS AI adoption half';
    chart.titleTextStyle.typeface='Arial';
    chart.titleTextStyle.fontSize=15;
    chart.setPosition('E2','P22');
    chart.xAxis={axisType:'textAxis',textStyle:{typeface:'Arial',fontSize:11}};
    chart.yAxis={numberFormatCode:'0.0',numberFormatSourceLinked:false,textStyle:{typeface:'Arial',fontSize:11}};
    chart.legend={position:'bottom',textStyle:{typeface:'Arial',fontSize:11}};
    chart.series.items[0].fill='#356A8A';chart.series.items[1].fill='#81559C';
  }
  const previewRange=spec.name==='Guide'?'A1:B9':spec.name==='AI halves'?'A1:P23':spec.name==='CES mapping'?'A1:D12':'A1:F12';
  const preview=await workbook.render({sheetName:spec.name,range:previewRange,scale:1.3,format:'png'});
  await fs.writeFile(path.join(out,`preview_${spec.name.replaceAll(' ','_')}.png`),new Uint8Array(await preview.arrayBuffer()));
}
const inspect=await workbook.inspect({kind:'table',range:'Productivity!A1:J8',include:'values,formulas',tableMaxRows:8,tableMaxCols:10,maxChars:3000});
await fs.writeFile(path.join(out,'workbook_inspection.ndjson'),inspect.ndjson);
const errors=await workbook.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:30},summary:'Formula error scan',maxChars:3000});
await fs.writeFile(path.join(out,'workbook_formula_scan.ndjson'),errors.ndjson);
console.log(errors.ndjson);
await fs.writeFile(path.join(out,'workbook_validation.json'),JSON.stringify(audits,null,2));
const file=await SpreadsheetFile.exportXlsx(workbook);
await file.save(path.join(out,'independent_quarterly_productivity.xlsx'));
console.log('Saved independent_quarterly_productivity.xlsx');
