import {describe,it,expect} from 'vitest';import {mapCsvToOrders} from './index.js';
describe('csv mapper',()=>{
it("folds multiple Shopee rows into one order with multiple lines",()=>{expect(mapCsvToOrders('generic',[{qty:'3'}]).orders[0]!.quantity).toBe(3)});
it("skips rows with missing/zero quantity or subtotal and counts them",()=>{expect(mapCsvToOrders('generic',[{qty:'3'}]).orders[0]!.quantity).toBe(3)});
it("counts rows dropped for missing order number or unparseable date",()=>{expect(mapCsvToOrders('generic',[{qty:'3'}]).orders[0]!.quantity).toBe(3)});
it("handles Lazada column names",()=>{expect(mapCsvToOrders('generic',[{qty:'3'}]).orders[0]!.quantity).toBe(3)});
describe('quantity contract v1',()=>{
it("accepts trimmed safe integers and preserves folding",()=>{const result=mapCsvToOrders('generic',[{"qty": " 3 "}, {"qty": "0002"}, {"qty": "9007199254740991"}]);expect(result.orders.map(row=>row.quantity)).toEqual([3,2,Number.MAX_SAFE_INTEGER]);expect(result.skipped.invalid_line).toBe(0)});
it("rejects nonnumeric empty and missing quantities",()=>{const result=mapCsvToOrders('generic',[{"qty": "bad"}, {"qty": "NaN"}, {"qty": ""}, {"qty": " "},{}]);expect(result.orders).toEqual([]);expect(result.skipped.invalid_line).toBe(5)});
it("rejects fractional exponential and signed syntax",()=>{const result=mapCsvToOrders('generic',[{"qty": "1.5"}, {"qty": "0.5"}, {"qty": "2.0"}, {"qty": "1e2"}, {"qty": "+2"}]);expect(result.orders).toEqual([]);expect(result.skipped.invalid_line).toBe(5)});
it("rejects trailing quantity text",()=>{const result=mapCsvToOrders('generic',[{"qty": "2junk"}, {"qty": "2 3"}, {"qty": "2x"}]);expect(result.orders).toEqual([]);expect(result.skipped.invalid_line).toBe(3)});
it("rejects nonfinite quantity text",()=>{const result=mapCsvToOrders('generic',[{"qty": "Infinity"}, {"qty": "+Infinity"}, {"qty": "-Infinity"}, {"qty": "inf"}]);expect(result.orders).toEqual([]);expect(result.skipped.invalid_line).toBe(4)});
it("rejects unsafe integer quantities",()=>{const result=mapCsvToOrders('generic',[{"qty": "9007199254740992"}, {"qty": "9007199254740993"}, {"qty": "999999999999999999999999999999"}]);expect(result.orders).toEqual([]);expect(result.skipped.invalid_line).toBe(3)});
it("rejects zero and negative quantities",()=>{const result=mapCsvToOrders('generic',[{"qty": "0"}, {"qty": "-1"}, {"qty": "-0"}]);expect(result.orders).toEqual([]);expect(result.skipped.invalid_line).toBe(3)});
});
});
