import {z} from 'zod';
export const mapCsvToOrders=(_source:string,rows:readonly Record<string,string>[])=>{
const out:{quantity:number}[]=[];let invalid_line=0;
for(const row of rows){z.record(z.string(),z.string()).parse(row);const qty=Number.parseInt(row['qty']??'0',10);
if(qty<=0){invalid_line++;continue}out.push({quantity:qty})}
return {orders:out,skipped:{invalid_line}}};
