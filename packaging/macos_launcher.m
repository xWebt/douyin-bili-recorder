#import <Foundation/Foundation.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

int main(int argc, char *argv[]) {
    @autoreleasepool {
        NSString *runtime_dir = [[[NSBundle mainBundle] resourcePath]
            stringByAppendingPathComponent:@"runtime"];
        NSString *executable = [runtime_dir
            stringByAppendingPathComponent:@"DouyinBiliRecorder"];

        if (![[NSFileManager defaultManager] isExecutableFileAtPath:executable]) {
            fprintf(stderr, "runtime executable missing: %s\n", [executable UTF8String]);
            return 127;
        }

        NSString *support_root = [NSSearchPathForDirectoriesInDomains(
            NSApplicationSupportDirectory,
            NSUserDomainMask,
            YES
        ) firstObject];
        NSString *working_dir = [support_root
            stringByAppendingPathComponent:@"DouyinBiliRecorder"];
        NSError *directory_error = nil;
        if (![[NSFileManager defaultManager]
                createDirectoryAtPath:working_dir
                withIntermediateDirectories:YES
                attributes:nil
                error:&directory_error]) {
            fprintf(stderr, "cannot create working directory: %s\n",
                    [[directory_error localizedDescription] UTF8String]);
            return 126;
        }

        if (chdir([working_dir fileSystemRepresentation]) != 0) {
            perror("chdir");
            return 126;
        }

        char *runtime_argv0 = strdup([executable fileSystemRepresentation]);
        if (runtime_argv0 == NULL) {
            perror("strdup");
            return 126;
        }
        if (argc > 0) {
            argv[0] = runtime_argv0;
        }

        execv([executable fileSystemRepresentation], argv);
        perror("execv");
        free(runtime_argv0);
        return 126;
    }
}
