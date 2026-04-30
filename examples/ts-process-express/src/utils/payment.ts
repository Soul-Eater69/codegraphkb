export interface RefundResult {
  ok: boolean;
  amount: number;
}

export function refundPayment(orderId: string, amount: number): RefundResult {
  return { ok: true, amount };
}
