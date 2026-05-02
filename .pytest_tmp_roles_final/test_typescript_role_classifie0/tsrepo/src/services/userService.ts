import { saveUserRepository } from '../repositories/userRepository';
export function createUserService(payload: any) {
  return saveUserRepository(payload);
}
