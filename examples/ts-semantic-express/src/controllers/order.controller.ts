import { cancelOrder, CancelInput } from "../services/order.service";

export function cancelOrderHandler(req: { params: { id: string }; body: { reason: string } }) {
  const input: CancelInput = { orderId: req.params.id, reason: req.body.reason };
  return cancelOrder(input);
}
