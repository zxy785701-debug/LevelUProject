import { Session } from './domain'
export function wrapText(text:string, measure:(s:string)=>number, width:number, max:number) {
  const rows:string[]=[];let line=''
  for(const c of text){
    if(c==='\n'){rows.push(line);line='';continue}
    if(line && measure(line+c)>width){rows.push(line);line=c}else line+=c
  }
  if(line)rows.push(line)
  if(rows.length>max){let last=rows[max-1];while(last && measure(last+'…')>width)last=last.slice(0,-1);rows[max-1]=last+'…'}
  return rows.slice(0,max)
}
export function posterContent(s:Session, quoteIndex:number) {
  const quotes=[s.report?.share_quote || '每个问题，都是理解的起点。',...(s.report?.summary||[])]
  return {title:`「${s.quiz.title}」`,quote:`“${quotes[quoteIndex%quotes.length]}”`,badge:`第 ${s.quiz.questions.length} 关 · 通关`}
}
