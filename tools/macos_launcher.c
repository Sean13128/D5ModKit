/* Finder launcher for the local Mac Python environment. */
#include <mach-o/dyld.h>
#include <limits.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <unistd.h>
#include <fcntl.h>

int main(void) {
    char executable[PATH_MAX], root[PATH_MAX], python[PATH_MAX], script[PATH_MAX];
    uint32_t size = sizeof(executable);
    if (_NSGetExecutablePath(executable, &size) || !realpath(executable, root)) return 1;
    for (int i = 0; i < 4; i++) {
        char *slash = strrchr(root, '/');
        if (!slash) return 1;
        *slash = '\0';
    }
    if (chdir(root)) return 1;
    int log = open("macos-launch.log", O_WRONLY | O_CREAT | O_APPEND, 0600);
    if (log >= 0) { dup2(log, STDOUT_FILENO); dup2(log, STDERR_FILENO); close(log); }
    if (snprintf(python, sizeof(python), "%s/.venv-macos/bin/python", root) >= (int)sizeof(python) ||
        snprintf(script, sizeof(script), "%s/D5ModKit.pyw", root) >= (int)sizeof(script)) return 1;
    char *args[] = {python, script, NULL};
    execv(python, args);
    perror("Could not start D5 Mod Kit");
    return 1;
}
