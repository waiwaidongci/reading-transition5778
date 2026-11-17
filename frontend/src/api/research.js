import {api} from './client.js';
export const sourcesApi={list:()=>api('/sources'),create:data=>api('/sources',{method:'POST',body:JSON.stringify(data)}),update:(id,data)=>api('/sources/'+id,{method:'PUT',body:JSON.stringify(data)}),records:id=>api('/sources/'+id+'/records'),add:(id,records)=>api('/sources/'+id+'/records',{method:'POST',body:JSON.stringify({records})})};
export const runsApi={list:()=>api('/runs'),get:id=>api('/runs/'+id),create:data=>api('/runs',{method:'POST',body:JSON.stringify(data)})};
export const notesApi={list:()=>api('/notes'),create:data=>api('/notes',{method:'POST',body:JSON.stringify(data)}),approve:id=>api('/notes/'+id+'/approve',{method:'POST'})};
export const dictionaryApi={
  versions:sourceId=>api('/sources/'+sourceId+'/dictionary/versions'),
  jobs:sourceId=>api('/sources/'+sourceId+'/dictionary/jobs'),
  preview:(sourceId,aliases)=>api('/sources/'+sourceId+'/dictionary/preview',{method:'POST',body:JSON.stringify({aliases})}),
  create:(sourceId,aliases)=>api('/sources/'+sourceId+'/dictionary/versions',{method:'POST',body:JSON.stringify({aliases})}),
  publish:versionId=>api('/dictionary/versions/'+versionId+'/publish',{method:'POST'}),
  retry:jobId=>api('/dictionary/jobs/'+jobId+'/retry',{method:'POST'}),
  revert:sourceId=>api('/sources/'+sourceId+'/dictionary/revert',{method:'POST'})
};
