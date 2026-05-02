export function saveUserRepository(user: any) {
  return prisma.user.create({ data: user });
}
