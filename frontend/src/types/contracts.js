/** @typedef {{id:number,name:string,source:string,rows:number,checksum:string}} Dataset */
/** @typedef {{id:number,name:string,dataset_id:number,status:string,result:Object,approved:boolean,approval_status:string,result_hash:string,created_by:number}} AnalysisJob */
/** @typedef {{id:number,name:string,job_id:number,destination:string,next_run:number,enabled:boolean,paused_reason:string}} ReportSchedule */
/** @typedef {{status:string,approved:boolean,required:number,received:number,result_hash:string,created_by:number,votes:Array,events:Array}} ApprovalDetail */
export {};
