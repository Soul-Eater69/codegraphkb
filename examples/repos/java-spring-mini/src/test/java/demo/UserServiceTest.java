package demo;

class UserServiceTest {
    void getUserReturnsEmail() {
        User user = new UserService().getUser("1");
        assert user.email().equals("ada@example.com");
    }
}
