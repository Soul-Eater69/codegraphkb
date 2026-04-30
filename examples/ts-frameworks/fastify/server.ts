import fastify from "fastify";

const server = fastify();

export function getHealth(req: any, reply: any) {
  return reply.send({ ok: true });
}

export function postOrder(req: any, reply: any) {
  return reply.send({ created: true });
}

export function authPreHandler(req: any, _reply: any, done: any) {
  done();
}

server.get("/health", getHealth);
server.route({
  method: "POST",
  url: "/orders",
  preHandler: authPreHandler,
  handler: postOrder,
});
