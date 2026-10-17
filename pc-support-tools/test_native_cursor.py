"""Compile the actual native cursor code against fake system boundaries."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
HARNESS = r'''
#import <Foundation/Foundation.h>
#import <GameController/GameController.h>
#import <dlfcn.h>
#import <objc/runtime.h>
static int calls, hides, unhides, failNext, failures;
static int Associate(BOOL value) {
    (void)value;
    calls++;
    if (failNext) { failNext=0; return 1000; }
    return 0;
}
static void *TestDlsym(void *handle, const char *name) {
    (void)handle; (void)name;
    return (void *)Associate;
}
static void Hide(id self, SEL cmd) { (void)self; (void)cmd; hides++; }
static void Unhide(id self, SEL cmd) { (void)self; (void)cmd; unhides++; }
#define dlsym TestDlsym
// SOURCE is the actual producer, with only its startup constructor disabled.
SOURCE
#undef dlsym
#define CHECK(condition) do { if (!(condition)) { \
    fprintf(stderr, "line %d: %s\n", __LINE__, #condition); failures++; } } while (0)
int main(void) {
    @autoreleasepool {
        Class cursor=objc_getClass("NSCursor");
        if (!cursor) {
            cursor=objc_allocateClassPair([NSObject class],"NSCursor",0);
            objc_registerClassPair(cursor);
        }
        class_replaceMethod(object_getClass(cursor),sel_registerName("hide"),(IMP)Hide,"v@:");
        class_replaceMethod(object_getClass(cursor),sel_registerName("unhide"),(IMP)Unhide,"v@:");
        wantLock=YES;
        Cursor(YES);
        CHECK(locked && hides==1 && unhides==0);
        failNext=1;
        Cursor(NO);
        CHECK(locked); // A failed release must remain retryable.
        int before=calls;
        Cursor(NO);
        CHECK(calls==before+1 && !locked);
        CHECK(hides==1 && unhides==1);
        before=unhides;
        failNext=1;
        Cursor(YES);
        CHECK(!locked && unhides==before); // Do not unhide another owner's cursor.
        Cursor(NO);
        CHECK(cursorError==0); // A safe unlocked state acknowledges capture failure.
        wantLock=YES;
        Cursor(YES);
        CHECK(locked && hides==2);
        inputTimer=[NSTimer timerWithTimeInterval:100 repeats:NO block:^(NSTimer *t){(void)t;}];
        failNext=1;
        Cleanup();
        CHECK(locked && inputTimer!=nil); // Shutdown must keep its release retry alive.
        Cleanup();
        CHECK(!locked && inputTimer==nil);
        CHECK(hides==2 && unhides==2);
        // Both free-cursor city drags and captured battle motion publish on
        // physical events, without waiting for a keyboard snapshot timer.
        CHECK(socketpair(AF_UNIX,SOCK_DGRAM,0,channels)==0);
        ready=YES;stopped=NO;locked=wantLock=NO;motionEvents=1;
        PublishMotion();
        char bytes[8192];
        ssize_t length=recv(channels[1],bytes,sizeof(bytes),MSG_DONTWAIT);
        CHECK(length>0);
        if (length>0) {
            NSDictionary *p=[NSJSONSerialization JSONObjectWithData:
                [NSData dataWithBytes:bytes length:length] options:0 error:nil];
            CHECK([p[@"kind"] isEqual:@"motion"] && ![p[@"locked"] boolValue]);
            CHECK(p[@"seq"]==nil && p[@"width"]!=nil && p[@"height"]!=nil);
            CHECK([p[@"dx"] doubleValue]==0 && motionEvents==0);
        }
        locked=wantLock=YES;dx=3.5;dy=-2;motionEvents=1;snapshotPending=YES;
        PublishMotion();
        CHECK(motionEvents==1 && dx==3.5); // Keyboard UP retains priority.
        snapshotPending=NO;
        PublishMotion();
        length=recv(channels[1],bytes,sizeof(bytes),MSG_DONTWAIT);
        CHECK(length>0 && dx==0 && dy==0 && motionEvents==0);
        if (length>0) {
            NSDictionary *p=[NSJSONSerialization JSONObjectWithData:
                [NSData dataWithBytes:bytes length:length] options:0 error:nil];
            CHECK([p[@"locked"] boolValue] && [p[@"dx"] doubleValue]==3.5);
        }
        close(channels[0]);close(channels[1]);channels[0]=channels[1]=-1;
    }
    return failures ? 1 : 0;
}
'''


@unittest.skipUnless(sys.platform == 'darwin', 'requires macOS native SDK')
class NativeCursorTests(unittest.TestCase):
    def test_failed_release_retries_and_cursor_hide_is_owned(self):
        source = (ROOT / 'IDVNativeInput.m').read_text()
        marker = '__attribute__((constructor)) static void Start(void)'
        self.assertEqual(source.count(marker), 1)
        source = source.replace(marker, 'static void Start(void)')
        with tempfile.TemporaryDirectory(prefix='idv-cursor-test-') as directory:
            path = Path(directory)
            unit, binary = path / 'test.m', path / 'test'
            unit.write_text(HARNESS.replace('SOURCE\n', source + '\n'))
            subprocess.run(['xcrun', 'clang', '-fobjc-arc', '-fblocks', '-Wall',
                            '-Wextra', '-Werror', '-Wno-unused-function',
                            '-framework', 'Foundation', '-framework', 'GameController',
                            '-framework', 'CoreGraphics',
                            str(unit), '-o', str(binary)], check=True, capture_output=True)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
