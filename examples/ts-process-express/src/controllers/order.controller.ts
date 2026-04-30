import { cancelOrder, CancelInput } from "../services/order.service";

export function cancelOrderHandler(req: any, res: any) {
  const input: CancelInput = { orderId: req.params.id, reason: req.body.reason };
  const result = cancelOrder(input);
  res.json(result);
}
