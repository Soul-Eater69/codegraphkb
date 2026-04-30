export async function GET(req: Request) {
  return new Response(JSON.stringify({ id: 1 }));
}

export async function DELETE(req: Request) {
  return new Response(null, { status: 204 });
}
