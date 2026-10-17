// Native Catalyst input producer. No touch simulation or PlayTools hooks.
#import <Foundation/Foundation.h>
#import <GameController/GameController.h>
#import <objc/message.h>
#import <objc/runtime.h>
#import <mach-o/dyld.h>
#import <mach-o/loader.h>
#import <dlfcn.h>
#import <sys/socket.h>
#import <fcntl.h>
#import <unistd.h>
#import <errno.h>
#import <math.h>

static int channels[2] = {-1, -1};
static BOOL ready, wantLock, locked, stopped;
static uint64_t sequence;
static double dx, dy, wheel;
static NSMutableArray *mouseEvents;
static id monitor;
static NSTimer *inputTimer;
static NSString *sourcePath;
static intptr_t slide;
static NSDate *lastBoot, *lastCommand;
static BOOL savedCoalescing, ownsCoalescing;
static BOOL ownsCursorHide;
static int cursorError;
static uint64_t motionEvents;
static double motionFirst, motionLast;
static BOOL snapshotPending;

static id Send(id obj, const char *sel) {
    return ((id(*)(id,SEL))objc_msgSend)(obj, sel_registerName(sel));
}
static BOOL Active(void) {
    id app = Send((id)objc_getClass("NSApplication"), "sharedApplication");
    return app && ((BOOL(*)(id,SEL))objc_msgSend)(app,sel_registerName("isActive"));
}
static void Coalescing(BOOL capture) {
    id cls=(id)objc_getClass("NSEvent");
    SEL getter=sel_registerName("isMouseCoalescingEnabled");
    SEL setter=sel_registerName("setMouseCoalescingEnabled:");
    if (!class_respondsToSelector(object_getClass(cls),getter) ||
        !class_respondsToSelector(object_getClass(cls),setter)) return;
    if (capture && !ownsCoalescing) {
        savedCoalescing=((BOOL(*)(id,SEL))objc_msgSend)(cls,getter);
        ((void(*)(id,SEL,BOOL))objc_msgSend)(cls,setter,NO);
        ownsCoalescing=YES;
    } else if (!capture && ownsCoalescing) {
        ((void(*)(id,SEL,BOOL))objc_msgSend)(cls,setter,savedCoalescing);
        ownsCoalescing=NO;
    }
}
static void Cursor(BOOL value) {
    // Finish an unsuccessful release before accepting a fresh capture request.
    if (cursorError && locked) value=NO;
    if (locked == value) {
        if (!value) cursorError=0; // Capture failed, but no association needs undoing.
        return;
    }
    // These macOS entry points exist in the Catalyst host, but are not declared
    // for Catalyst SDK clients. Resolve them without changing shared frameworks.
    int (*associate)(BOOL) = dlsym(RTLD_DEFAULT,"CGAssociateMouseAndMouseCursorPosition");
    int error=associate ? associate(!value) : -1;
    if (error) {
        if (cursorError!=error) NSLog(@"IDVPC cursor association failed %d",error);
        cursorError=error;wantLock=NO;
        // Retain the successfully applied association state so release retries
        // are not skipped. Only undo this module's own hide on any failure.
        if (ownsCursorHide) {Send((id)objc_getClass("NSCursor"),"unhide");ownsCursorHide=NO;}
        Coalescing(NO);
        dx=dy=0;motionEvents=0;motionFirst=motionLast=0;
        return;
    }
    cursorError=0;
    if (value && !ownsCursorHide) {Send((id)objc_getClass("NSCursor"),"hide");ownsCursorHide=YES;}
    if (!value && ownsCursorHide) {Send((id)objc_getClass("NSCursor"),"unhide");ownsCursorHide=NO;}
    locked = value;
    Coalescing(value);
    dx = dy = 0;
    motionEvents=0;motionFirst=motionLast=0;
}
static BOOL Capturing(void) {return locked && wantLock && !cursorError;}
static void Cleanup(void) {
    ready=NO;wantLock=NO;
    Cursor(NO);Coalescing(NO);
    // Keep the existing main-run-loop timer only while system release needs
    // retrying. The stopped Tick path cannot bootstrap or process new input.
    if (!locked) {[inputTimer invalidate];inputTimer=nil;}
    if (monitor) {
        ((void(*)(id,SEL,id))objc_msgSend)((id)objc_getClass("NSEvent"),sel_registerName("removeMonitor:"),monitor);
        monitor=nil;
    }
    [mouseEvents removeAllObjects];
    for (int i=0;i<2;i++) if (channels[i]>=0) {close(channels[i]);channels[i]=-1;}
}
static NSDictionary *Pointer(void) {
    id app=Send((id)objc_getClass("NSApplication"),"sharedApplication");
    id window=Send(app,"keyWindow");
    CGPoint pos=window ? ((CGPoint(*)(id,SEL))objc_msgSend)(window,sel_registerName("mouseLocationOutsideOfEventStream")) : CGPointZero;
    CGRect rect=window ? ((CGRect(*)(id,SEL))objc_msgSend)(Send(window,"contentView"),sel_registerName("bounds")) : CGRectZero;
    return @{@"x":@(pos.x),@"y":@(pos.y),@"width":@(rect.size.width),@"height":@(rect.size.height)};
}
static void PublishMotion(void) {
    if (!ready || stopped || !motionEvents || snapshotPending) return;
    // Send on the physical event, not on the independent 120 Hz snapshot timer.
    // Keep unsent displacement for the next event/snapshot if the channel fills.
    NSMutableDictionary *packet=[@{@"kind":@"motion",@"active":@YES,@"locked":@(Capturing()),
        @"dx":@(Capturing()?dx:0),@"dy":@(Capturing()?dy:0),@"motion_events":@(motionEvents),
        @"motion_first":@(motionFirst),@"motion_last":@(motionLast),
        @"sent":@(NSProcessInfo.processInfo.systemUptime)} mutableCopy];
    [packet addEntriesFromDictionary:Pointer()];
    NSError *error=nil;
    NSData *data=[NSJSONSerialization dataWithJSONObject:packet options:0 error:&error];
    if (!data) {NSLog(@"IDVPC motion encode failed %@",error);return;}
    if (send(channels[0],data.bytes,data.length,MSG_DONTWAIT)>=0) {
        dx=dy=0;motionEvents=0;motionFirst=motionLast=0;
    } else if (errno!=EAGAIN && errno!=ENOBUFS) {
        NSLog(@"IDVPC motion channel error %d",errno);stopped=YES;Cursor(NO);
    }
}
static unsigned VK(unsigned hid) {
    if (hid >= 4 && hid <= 29) return 'A' + hid - 4;
    if (hid >= 30 && hid <= 38) return '1' + hid - 30;
    if (hid >= 58 && hid <= 69) return 112 + hid - 58;
    if (hid >= 89 && hid <= 97) return 97 + hid - 89;
    switch (hid) {
        case 39:return 48; case 40:case 88:return 13; case 41:return 27;
        case 42:return 8; case 43:return 9; case 44:return 32;
        case 45:return 189; case 46:return 187; case 47:return 219;
        case 48:return 221; case 49:return 220; case 51:return 186;
        case 52:return 222; case 53:return 192; case 54:return 188;
        case 55:return 190; case 56:return 191; case 57:return 20;
        case 73:return 45; case 74:return 36; case 75:return 33;
        case 76:return 46; case 77:return 35; case 78:return 34;
        case 79:return 39; case 80:return 37; case 81:return 40; case 82:return 38;
        case 84:return 111; case 85:return 106; case 86:return 109;
        case 87:return 107; case 98:return 96; case 99:return 110;
        case 224:case 228:return 17; case 225:case 229:return 16;
        case 226:case 230:return 18; case 227:return 91; case 231:return 92;
        default:return 0;
    }
}
static void ReceiveCommands(void) {
    char buffer[4096]; ssize_t count;
    while ((count=recv(channels[0],buffer,sizeof(buffer),MSG_DONTWAIT))>0) {
        NSError *error=nil;
        id cmd=[NSJSONSerialization JSONObjectWithData:[NSData dataWithBytes:buffer length:count] options:0 error:&error];
        if (![cmd isKindOfClass:[NSDictionary class]]) {
            NSLog(@"IDVPC invalid command %@",error); continue;
        }
        lastCommand=[NSDate date];
        if ([cmd[@"ready"] boolValue]) {ready=YES;NSLog(@"IDVPC Python adapter ready");}
        if (cmd[@"lock"]) wantLock=[cmd[@"lock"] boolValue];
        if ([cmd[@"stop"] boolValue]) {stopped=YES;wantLock=NO;}
    }
}
static void Bootstrap(void) {
    if (ready || (lastBoot && -[lastBoot timeIntervalSinceNow]<1.0)) return;
    lastBoot=[NSDate date];
    // Exact-build CPython 3.11 addresses, validated before scheduling this timer.
    // The interpreter must exist. The current tstate is normally NULL between
    // engine frames because it releases the GIL while servicing the run loop.
    if (!*(void **)(slide+0x107b85f38)) return;
    int (*ensure)(void)=(void *)(slide+0x1050be054);
    void (*release)(int)=(void *)(slide+0x1050be10c);
    void *(*builtins)(void)=(void *)(slide+0x105079920);
    void *(*run)(const char*,int,void*,void*,void*)=(void *)(slide+0x1050bf9e8);
    void (*printError)(void)=(void *)(slide+0x1050bf9d4);
    int state=ensure();
    // Install presentation/input gates after managers and key data exist, before
    // a player unit or hall UI is created. Do not wait for entering a world.
    // JSON string literals are valid Python literals for paths (no booleans/null).
    NSData *paths=[NSJSONSerialization dataWithJSONObject:@[sourcePath,sourcePath.stringByDeletingLastPathComponent] options:NSJSONWritingFragmentsAllowed error:nil];
    NSArray *quoted=[NSJSONSerialization JSONObjectWithData:paths options:0 error:nil];
    NSData *q0=[NSJSONSerialization dataWithJSONObject:quoted[0] options:NSJSONWritingFragmentsAllowed|NSJSONWritingWithoutEscapingSlashes error:nil];
    NSData *q1=[NSJSONSerialization dataWithJSONObject:quoted[1] options:NSJSONWritingFragmentsAllowed|NSJSONWritingWithoutEscapingSlashes error:nil];
    NSString *pathLiteral=[[NSString alloc] initWithData:q0 encoding:NSUTF8StringEncoding];
    NSString *dirLiteral=[[NSString alloc] initWithData:q1 encoding:NSUTF8StringEncoding];
    NSString *inner=[NSString stringWithFormat:@"import sys\nm=sys.modules.get('game_init')\ngk=getattr(m,'GK',None)\nif gk and getattr(gk,'g_ui_mgr',None) and getattr(gk,'g_key_handler_mgr',None) and getattr(getattr(gk,'DM',None),'pc_setting_data',None):\n exec(compile(open(%@,encoding='utf-8').read(),%@,'exec'),{'NATIVE_FD':%d,'SUPPORT_DIR':%@})\n",pathLiteral,pathLiteral,channels[1],dirLiteral];
    NSData *escaped=[NSJSONSerialization dataWithJSONObject:inner options:NSJSONWritingFragmentsAllowed|NSJSONWritingWithoutEscapingSlashes error:nil];
    NSString *code=[NSString stringWithFormat:@"exec(%@,{})",[[NSString alloc] initWithData:escaped encoding:NSUTF8StringEncoding]];
    void *dict=builtins();
    void *result=run(code.UTF8String,257,dict,dict,NULL);
    if (!result) {NSLog(@"IDVPC bootstrap failed");printError();}
    else if (--*(int64_t *)result==0) ((void(*)(void*))(slide+0x104fbc4e4))(result);
    release(state);
}
static void Tick(void) {
    ReceiveCommands();
    BOOL active=Active();
    if (lastCommand && -[lastCommand timeIntervalSinceNow]>0.5) wantLock=NO;
    Cursor(wantLock && active && !stopped);
    if (stopped) { Cleanup(); return; }
    Bootstrap();
    if (!ready) return;
    NSMutableSet *keys=[NSMutableSet set];
    GCKeyboardInput *input=GCKeyboard.coalescedKeyboard.keyboardInput;
    if (active && input) for (unsigned hid=4;hid<=231;hid++) {
        unsigned vk=VK(hid);
        if (vk && [input buttonForKeyCode:(GCKeyCode)hid].pressed) [keys addObject:@(vk)];
    }
    NSMutableDictionary *packet=[@{@"seq":@(sequence++),@"active":@(active),@"keys":keys.allObjects,@"events":[mouseEvents copy],@"dx":@(Capturing()?dx:0),@"dy":@(Capturing()?dy:0),@"wheel":@(wheel),@"locked":@(Capturing()),@"cursor_error":@(cursorError),@"motion_events":@(motionEvents),@"motion_first":@(motionFirst),@"motion_last":@(motionLast),@"sent":@(NSProcessInfo.processInfo.systemUptime)} mutableCopy];
    [packet addEntriesFromDictionary:Pointer()];
    NSError *error=nil;
    NSData *data=[NSJSONSerialization dataWithJSONObject:packet options:0 error:&error];
    if (!data) {NSLog(@"IDVPC encode failed %@",error);return;}
    if (send(channels[0],data.bytes,data.length,MSG_DONTWAIT)>=0) {
        [mouseEvents removeAllObjects];dx=dy=wheel=0;
        motionEvents=0;motionFirst=motionLast=0;
        snapshotPending=NO;
    } else if (errno==EAGAIN || errno==ENOBUFS) {
        // Do not let high-rate motion starve keyboard release snapshots.
        snapshotPending=YES;
    } else {NSLog(@"IDVPC socket send error %d",errno);stopped=YES;Cursor(NO);}
    if (mouseEvents.count>256) {NSLog(@"IDVPC mouse queue overflow; releasing cursor");[mouseEvents removeAllObjects];wantLock=NO;}
}
__attribute__((constructor)) static void Start(void) {
    @autoreleasepool {
        slide=_dyld_get_image_vmaddr_slide(0);
        const struct mach_header_64 *header=(const void *)_dyld_get_image_header(0);
        const uint8_t expectedUUID[16]={0x36,0x4b,0xd2,0xd4,0xb1,0x1f,0x34,0xf2,0x8e,0x27,0x69,0x5c,0xed,0xaa,0x4f,0xe8};
        BOOL uuidMatches=NO;
        const uint8_t *command=(const void *)(header+1);
        const uint8_t *end=command+header->sizeofcmds;
        for (uint32_t i=0;i<header->ncmds && command+sizeof(struct load_command)<=end;i++) {
            const struct load_command *lc=(const void *)command;
            if (lc->cmdsize<sizeof(*lc) || command+lc->cmdsize>end) break;
            if (lc->cmd==LC_UUID && lc->cmdsize>=sizeof(struct uuid_command))
                uuidMatches=memcmp(((const struct uuid_command *)lc)->uuid,expectedUUID,16)==0;
            command+=lc->cmdsize;
        }
        if (!uuidMatches) {NSLog(@"IDVPC unsupported executable UUID; disabled");return;}
        NSString *disabled=[NSHomeDirectory() stringByAppendingPathComponent:@"Documents/idv-pc-support-disabled"];
        if ([[NSFileManager defaultManager] fileExistsAtPath:disabled]) {NSLog(@"IDVPC disabled by user");return;}
        // Fail closed on unsupported executables, even when installed manually.
        if (*(uint32_t *)(slide+0x1050be054)!=0xa9be4ff4 ||
            *(uint32_t *)(slide+0x1050bf9e8)!=0xd10183ff) {
            NSLog(@"IDVPC unsupported Python runtime; disabled"); return;
        }
        Dl_info info;
        if (!dladdr((void *)Start,&info) || !info.dli_fname) return;
        sourcePath=[[[NSString stringWithUTF8String:info.dli_fname] stringByDeletingLastPathComponent] stringByAppendingPathComponent:@"runtime_adapter.py"];
        if (socketpair(AF_UNIX,SOCK_DGRAM,0,channels)!=0) {NSLog(@"IDVPC socketpair failed %d",errno);return;}
        for (int i=0;i<2;i++) {
            if (fcntl(channels[i],F_SETFL,O_NONBLOCK)<0 || fcntl(channels[i],F_SETFD,FD_CLOEXEC)<0) {NSLog(@"IDVPC fcntl failed %d",errno);close(channels[0]);close(channels[1]);return;}
        }
        mouseEvents=[NSMutableArray array];
        dispatch_async(dispatch_get_main_queue(),^{
            uint64_t mask=0;
            int types[]={1,2,3,4,5,6,7,22,25,26,27};
            for (unsigned i=0;i<sizeof(types)/sizeof(*types);i++) mask|=1ULL<<types[i];
            monitor=((id(*)(id,SEL,uint64_t,id))objc_msgSend)((id)objc_getClass("NSEvent"),sel_registerName("addLocalMonitorForEventsMatchingMask:handler:"),mask,^id(id event){
                long type=((long(*)(id,SEL))objc_msgSend)(event,sel_registerName("type"));
                if (!ready || stopped || !Active()) return event;
                if (type==5 || type==6 || type==7 || type==27) {
                    double mx=((double(*)(id,SEL))objc_msgSend)(event,sel_registerName("deltaX"));
                    double my=((double(*)(id,SEL))objc_msgSend)(event,sel_registerName("deltaY"));
                    if (isfinite(mx) && isfinite(my)) {
                        if (Capturing()) {dx+=mx;dy+=my;}
                        motionLast=((double(*)(id,SEL))objc_msgSend)(event,sel_registerName("timestamp"));
                        if (!motionEvents) motionFirst=motionLast;
                        motionEvents++;
                        PublishMotion();
                    }
                } else if (type==22) {
                    double delta=((double(*)(id,SEL))objc_msgSend)(event,sel_registerName("scrollingDeltaY"));
                    if (isfinite(delta) && isfinite(wheel+delta)) wheel+=delta;
                }
                else {
                    long button=((long(*)(id,SEL))objc_msgSend)(event,sel_registerName("buttonNumber"));
                    unsigned key=button==0?1:button==1?2:button==2?4:0;
                    if (key) [mouseEvents addObject:@[@((type==1||type==3||type==25)?1:2),@(key),@(Capturing())]];
                }
                return Capturing() ? nil : event;
            });
            inputTimer=[NSTimer scheduledTimerWithTimeInterval:1.0/120.0 repeats:YES block:^(NSTimer *t){(void)t;Tick();}];
            [[NSRunLoop mainRunLoop] addTimer:inputTimer forMode:NSRunLoopCommonModes];
            NSLog(@"IDVPC input producer started v8");
        });
    }
}
