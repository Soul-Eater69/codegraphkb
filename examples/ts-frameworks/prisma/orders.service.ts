import { PrismaClient } from "@prisma/client";

const prisma = new PrismaClient();

export async function listOrders(userId: string) {
  return prisma.order.findMany({ where: { userId } });
}

export async function cancelOrder(id: string) {
  await prisma.order.update({ where: { id }, data: { status: "cancelled" } });
  await prisma.refund.create({ data: { orderId: id, amount: 100 } });
}
