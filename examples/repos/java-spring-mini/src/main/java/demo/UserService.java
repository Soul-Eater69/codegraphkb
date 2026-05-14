package demo;

public class UserService {
    public User getUser(String id) {
        return new User(id, "ada@example.com");
    }
}
