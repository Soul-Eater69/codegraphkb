import { cancelOrderHandler } from "../controllers/order.controller";

interface RouterLike {
  post(path: string, handler: (req: any, res: any) => any): void;
}

export function registerOrderRoutes(router: RouterLike): void {
  router.post("/orders/:id/cancel", (req, res) => {
    const result = cancelOrderHandler(req);
    res.json(result);
  });
}
