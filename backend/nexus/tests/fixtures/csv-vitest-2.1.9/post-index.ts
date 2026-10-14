import {z} from 'zod';
export const mapCsvToOrders=(_source:string,rows:readonly Record<string,string>[])=>{
const out:{quantity:number}[]=[];let invalid_line=0;
for(const row of rows){z.record(z.string(),z.string()).parse(row);const text=(row['qty']??'').trim();const qty=/^\d+$/.test(text)?Number(text):Number.NaN;
if(!Number.isSafeInteger(qty)||qty<=0){invalid_line++;continue}out.push({quantity:qty})}
return {orders:out,skipped:{invalid_line}}};
