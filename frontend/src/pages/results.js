import {jobs} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {chart} from '../components/common/chart.js';
import {table} from '../components/common/table.js';
import {status} from '../components/common/status.js';
import {ApprovalAction,PausedReason} from '../constants/enums.js';
import {esc,fmt,date,notify} from '../utils/dom.js';

function approvalPanel(j,a){
 const mine=(a.votes||[]).find(v=>v.user_id===session.user.id);
 const canSign=session.user.role==='admin'&&j.status==='completed'&&j.created_by!==session.user.id;
 const active=mine&&mine.state==='active'&&mine.current_result;
 const progress='<div class="signature-progress">'+Array.from({length:a.required},(_,i)=>'<span class="'+(i<a.received?'filled':'')+'">'+(i<a.received?'已签':'待签')+'</span>').join('')+'<strong>'+a.received+' / '+a.required+'</strong></div>';
 const voteList=(a.votes||[]).length?'<ul class="vote-list">'+a.votes.map(v=>'<li class="'+(v.state==='active'&&v.current_result?'active':'revoked')+'"><div><strong>'+esc(v.approver_name||v.approver_email)+'</strong><span>'+(v.state==='active'&&v.current_result?'有效签署':'已撤回')+(v.current_result?'':' · 非当前结果')+'</span></div><p>'+esc(v.opinion||'未填写意见')+'</p><small>'+date(v.signed_at)+(v.revoked_at?' · 撤于 '+date(v.revoked_at):'')+(v.revoke_reason?' · '+esc(v.revoke_reason):'')+'</small></li>').join('')+'</ul>':'<p class="empty">尚无签署记录。需要两名不同业务负责人共同复核。</p>';
 const timeline=(a.events||[]).length?'<ol class="review-timeline">'+a.events.map(e=>'<li><strong>'+esc(ApprovalAction[e.action]||e.action)+'</strong><span>'+esc(e.actor_name||e.actor_email||'系统')+' · '+date(e.at)+'</span>'+(e.opinion?'<p>意见：'+esc(e.opinion)+'</p>':'')+(e.note?'<p>说明：'+esc(e.note)+'</p>':'')+'</li>').join('')+'</ol>':'';
 const action=canSign&&!active?('<form id="sign-form" class="sign-form"><label>复核意见（随票保留）<textarea name="opinion" rows="2" maxlength="600" placeholder="记录复核依据、疑点或保留意见"></textarea></label><button class="primary" type="submit">'+(a.received?'签署第二票':'签署复核票')+'</button></form>'):(active?'<form id="revoke-form" class="sign-form"><label>撤签说明<textarea name="note" rows="2" maxlength="300" placeholder="撤回原因会记入结果页"></textarea></label><button class="button" type="submit">撤回我的签署</button></form>':'');
 const blocked=j.created_by===session.user.id?'<p class="hint">你是本次分析的发起人，必须回避，不能签署自己的结论。</p>':(session.user.role!=='admin'?'<p class="hint">仅业务负责人可以签署或撤回。</p>':'');
 return '<section class="panel approval-panel"><div class="section-title"><h2>复核签署</h2><span>'+(a.status==='approved'?'双人复核完成':a.received?'已获 '+a.received+' 票，待第二票':'待两名负责人复核')+'</span></div>'+progress+'<p class="hint">每票绑定签署当时的结果指纹 '+esc((a.result_hash||'').slice(0,16))+'…；同一负责人重复签署不重复计票。</p>'+voteList+'<div class="approval-actions">'+action+'</div>'+blocked+(timeline?'<div class="section-title compact-title"><h3>签署与撤签经过</h3></div>'+timeline:'')+'</section>';
}

export async function results(id){
 workspace.jobs=await jobs.list();const j=id?await jobs.get(id):(workspace.jobs.find(j=>j.id===workspace.selectedJob)||workspace.jobs[0]);
 if(j&&!workspace.jobs.some(x=>x.id===j.id))workspace.jobs.push(j);
 if(!j)return heading('04 / REVIEW','结果复核','尚无分析结果。')+'<div class="empty">先到分析工作台，选择批次并提交一次计算。<a href="#/workbench">前往工作台 ↗</a></div>';
 workspace.selectedJob=j.id;const r=j.result||{};
 const a=await jobs.approvals(j.id);
 const label=a.status==='approved'?'双人复核完成':(a.received?'待第二票（'+a.received+' / '+a.required+'）':'待两人复核');
 return heading('04 / REVIEW','结果复核与业务解释',j.name,'<button class="button" id="refresh-results">刷新结果 ↻</button>')+'<div class="result-selector"><label>分析记录<select id="select-job">'+workspace.jobs.map(x=>'<option value="'+x.id+'" '+(x.id===j.id?'selected':'')+'>'+esc(x.name)+' · '+esc(x.status)+'</option>').join('')+'</select></label>'+status(j.status)+'<span>'+date(j.created_at)+'</span><span class="approval">'+esc(label)+'</span></div>'+(j.status==='completed'?'<section class="result-lead"><p class="eyebrow">COMPUTED FINDING</p><h2>'+esc(r.summary)+'</h2><div class="metrics">'+(r.metrics||[]).map(m=>'<div><span>'+esc(m.label)+'</span><strong>'+esc(fmt(m.value))+'<small>'+esc(m.unit||'')+'</small></strong></div>').join('')+'</div></section><section class="panel">'+chart(r.chart)+'</section><div class="two-columns"><section class="panel"><div class="section-title"><h2>业务解释</h2><span>由计算结果生成</span></div><ol class="questions">'+(r.findings||[]).map(v=>'<li>'+esc(v)+'</li>').join('')+'</ol>'+(r.warnings||[]).map(v=>'<p class="warning">'+esc(v)+'</p>').join('')+'</section><section class="method-sheet compact"><p class="eyebrow">REPRODUCIBILITY</p><h3>计算口径与参数</h3><p>'+esc(r.method)+'</p><pre>'+esc(JSON.stringify(j.params,null,2))+'</pre><p class="hint">仅完成双人复核的结果可进入定时分发档案。</p></section></div>'+approvalPanel(j,a)+'<section class="panel"><div class="section-title"><h2>结果明细</h2><span>'+(r.table?.rows?.length||0)+' 行</span></div>'+table(r.table?.columns||[],r.table?.rows||[])+'</section>':'<section class="panel empty">'+(j.status==='failed'?'计算失败：'+esc(j.error)+'。请返回工作台调整参数或数据。':'后台正在执行计算。点击刷新结果查看最新进展。')+'<a href="#/workbench">返回工作台 ↗</a></section>');
}
export function bindResults(refresh){
 document.querySelector('#refresh-results')?.addEventListener('click',refresh);
 document.querySelector('#select-job')?.addEventListener('change',e=>{workspace.selectedJob=Number(e.target.value);location.hash='#/results/'+e.target.value;});
 document.querySelector('#sign-form')?.addEventListener('submit',async e=>{e.preventDefault();const f=new FormData(e.target);try{await jobs.sign(workspace.selectedJob,f.get('opinion'));notify('签署已记录');await refresh();}catch(err){notify(err.message,true);}});
 document.querySelector('#revoke-form')?.addEventListener('submit',async e=>{e.preventDefault();const f=new FormData(e.target);try{await jobs.revoke(workspace.selectedJob,f.get('note'));notify('已撤签，分析退回待复核，关联计划已暂停');await refresh();}catch(err){notify(err.message,true);}});
}
