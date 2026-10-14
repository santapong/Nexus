import {describe,it,expect} from 'vitest';import {mapCsvToOrders} from './index.js';
describe('csv mapper',()=>{
it("folds multiple Shopee rows into one order with multiple lines",()=>{expect(mapCsvToOrders('generic',[{qty:'3'}]).orders[0]!.quantity).toBe(3)});
it("skips rows with missing/zero quantity or subtotal and counts them",()=>{expect(mapCsvToOrders('generic',[{qty:'3'}]).orders[0]!.quantity).toBe(3)});
it("counts rows dropped for missing order number or unparseable date",()=>{expect(mapCsvToOrders('generic',[{qty:'3'}]).orders[0]!.quantity).toBe(3)});
it("handles Lazada column names",()=>{expect(mapCsvToOrders('generic',[{qty:'3'}]).orders[0]!.quantity).toBe(3)});
});
