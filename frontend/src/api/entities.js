import {api} from './client.js';
export const datasets={list:()=>api('/datasets'),get:id=>api('/datasets/'+id),create:data=>api('/datasets',{method:'POST',body:JSON.stringify(data)})};
export const jobs={
 list:()=>api('/jobs'),
 get:id=>api('/jobs/'+id),
 create:data=>api('/jobs',{method:'POST',body:JSON.stringify(data)}),
 approvals:id=>api('/jobs/'+id+'/approvals'),
 sign:(id,opinion)=>api('/jobs/'+id+'/approvals/sign',{method:'POST',body:JSON.stringify({opinion:opinion||''})}),
 revoke:(id,note)=>api('/jobs/'+id+'/approvals/revoke',{method:'POST',body:JSON.stringify({note:note||''})}),
 approve:id=>api('/jobs/'+id+'/approvals/sign',{method:'POST',body:JSON.stringify({})})
};
export const reports={list:()=>api('/reports'),create:data=>api('/reports',{method:'POST',body:JSON.stringify(data)}),toggle:id=>api('/reports/'+id+'/toggle',{method:'POST'}),deliveries:()=>api('/deliveries')};
