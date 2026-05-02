import { createUserService } from '../services/userService';
export function createUserHandler(req: any) {
  return createUserService(req.body);
}
