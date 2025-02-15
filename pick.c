#define _GNU_SOURCE
#include <assert.h>
#include <sqlite3.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

#define CLEANUP(func) __attribute__((cleanup(func)))

static sqlite3 *open_sqlite_connection(void)
{
    const char *home = getenv("HOME");
    char path[4096];
    snprintf(path, sizeof(path), "%s/.local/share/pyclipmon/history.sqlite3", home);

    sqlite3 *db;
    int res = sqlite3_open(path, &db);
    if (res) {
        fprintf(stderr, "failed to open sqlite database: %s: %s (%m)\n", path, sqlite3_errstr(res));
        return NULL;
    }

    return db;
}

static void cleanup_connection(sqlite3 **conn)
{
    if (*conn)
        sqlite3_close(*conn);
}

static void cleanup_statement(sqlite3_stmt **stmt)
{
    if (*stmt)
        sqlite3_finalize(*stmt);
}

static void cleanup_fd(int *fd)
{
    if (*fd >= 0)
        close(*fd);
}

static void cleanup_file(FILE **fp)
{
    if (*fp)
        fclose(*fp);
}

static int read_history(sqlite3 *conn)
{
    int fd = memfd_create("fuzzel-input", MFD_CLOEXEC);
    assert(fd >= 0);

    CLEANUP(cleanup_file) FILE *fp = fdopen(fd, "w");
    assert(fp != NULL);

    const char *sql = "SELECT DISTINCT text FROM history ORDER BY timestamp DESC";
    CLEANUP(cleanup_statement) sqlite3_stmt *stmt = NULL;
    int res = sqlite3_prepare_v2(conn, sql, -1, &stmt, NULL);
    if (res) {
        fprintf(stderr, "failed to execute sql query: %s\n", sqlite3_errstr(res));
        return -1;
    }

    while (true) {
        res = sqlite3_step(stmt);

        if (res == SQLITE_ROW) {
            const unsigned char *text = sqlite3_column_text(stmt, 0);
            fputs((char *)text, fp);
            fputc('\0', fp);

        } else if (res == SQLITE_DONE) {
            fflush(fp);
            fd = dup(fd);
            assert(fd >= 0);
            assert(lseek(fd, 0, SEEK_SET) == 0);
            return fd;

        } else {
            fprintf(stderr, "failed to execute sql query: %s\n", sqlite3_errstr(res));
            return -1;
        }
    }

    abort();
}

static int spawn(const char *exe, char **argv, int stdin_fd)
{
    int stdout = memfd_create("spawn", MFD_CLOEXEC);
    assert(stdout >= 0);

    pid_t pid = fork();
    if (pid < 0) {
        perror("fork");
        close(stdout);
        return -1;
    }

    if (pid == 0) {
        dup2(stdin_fd, STDIN_FILENO);
        dup2(stdout, STDOUT_FILENO);
        if (execvp(exe, argv) < 0)
            perror("execvp");
        exit(1);
    }

    int status;
    if (waitpid(pid, &status, 0) < 0) {
        perror("waitpid");
        close(stdout);
        return -1;
    }
    if (!(WIFEXITED(status) && WEXITSTATUS(status) == 0)) {
        fprintf(stderr, "%s failed with exit code %d\n", exe, WEXITSTATUS(status));
        return -1;
    }

    return stdout;
}

int main(int argc, char *argv[])
{
    CLEANUP(cleanup_connection) sqlite3 *conn = open_sqlite_connection();
    if (!conn)
        return 1;

    CLEANUP(cleanup_fd) int stdin_fd = read_history(conn);
    if (stdin_fd < 0)
        return 1;

    char *spawn_argv[] = {"fuzzel", "--dmenu0", NULL};
    CLEANUP(cleanup_fd) int stdout_fd = spawn("fuzzel", spawn_argv, stdin_fd);
    if (stdout_fd < 0)
        return 1;

    struct stat statbuf;
    assert(fstat(stdout_fd, &statbuf) == 0);
    if (!statbuf.st_size)
        /* user cancelled fuzzel */
        return 0;
    /* remove trailing newspace */
    assert(ftruncate(stdout_fd, statbuf.st_size - 1) == 0);
    assert(lseek(stdout_fd, 0, SEEK_SET) == 0);

    char *wl_spawn_argv[] = {"wl-copy", NULL};
    CLEANUP(cleanup_fd) int stdout_fd2 = spawn("wl-copy", wl_spawn_argv, stdout_fd);
    if (stdout_fd2 < 0)
        return 1;

    return 0;
}
