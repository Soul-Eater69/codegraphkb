import { refundPayment, RefundResult } from "../utils/payment";

export interface CancelInput {
  orderId: string;
  reason: string;
}

export function cancelOrder(input: CancelInput): RefundResult {
  return refundPayment(input.orderId, 100);
}
