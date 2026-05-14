package demo;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class UserController {
    private final UserService service = new UserService();

    @GetMapping("/users/{id}")
    public User getUser(@PathVariable String id) {
        return service.getUser(id);
    }
}
