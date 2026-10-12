// Deliberately optional: no unimplemented endpoint is called by the MVP UI.
export interface FutureFeatures {
  login?: (code:string)=>Promise<{token:string}>
  parseSource?: (source:{type:'document'|'url'|'video';value:string})=>Promise<{text:string}>
  knowledgeLibrary?: ()=>Promise<unknown[]>
  profile?: ()=>Promise<unknown>
  review?: ()=>Promise<unknown>
  leaderboard?: ()=>Promise<unknown[]>
  vip?: ()=>Promise<unknown>
}
export const futureFeatures:FutureFeatures={}
