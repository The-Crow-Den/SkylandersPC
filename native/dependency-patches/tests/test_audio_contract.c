// SPDX-License-Identifier: GPL-2.0-or-later
// Build with -I <provider>/src and SDL3 flags. Uses the silent timer sink.
#include "runtime_audio.c"
#include <assert.h>
#include <sys/mman.h>
#include <unistd.h>

uintptr_t runtime_lookup(const RuntimeExport *table,size_t count,const char *name) {
    for(size_t i=0;i<count;++i)if(!strcmp(table[i].name,name))return (uintptr_t)table[i].function;
    return 0;
}
int main(void) {
    setenv("BB_AUDIO","none",1);
    assert(audio_init()==0);
    const int a=audio_open(0x1000,0,0,256,48000,5);
    const int b=audio_open(0x1000,0,0,256,48000,2);
    const int c=audio_open(0x1000,0,0,512,48000,2);
    assert(a>=0 && b>=0 && c>=0);
    const long page=sysconf(_SC_PAGESIZE);
    char *memory=mmap(NULL,(size_t)page*2,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
    assert(memory!=MAP_FAILED && mprotect(memory+page,(size_t)page,PROT_NONE)==0);
    int32_t *scalar=(int32_t *)(memory+page-sizeof(int32_t));*scalar=12345;
    assert(audio_volume(a,0xff,scalar)==0);
    for(int i=0;i<8;++i)assert(ports[a&0xff].volume[i]==12345);
    *scalar=0;assert(audio_volume(a,0xff,scalar)==0);
    for(int i=0;i<8;++i)assert(ports[a&0xff].volume[i]==0);
    *scalar=VOLUME_0DB;assert(audio_volume(a,3,scalar)==0);
    assert(ports[a&0xff].volume[0]==VOLUME_0DB && ports[a&0xff].volume[2]==0);
    *scalar=VOLUME_0DB+1;assert(audio_volume(a,0xff,scalar)==ERR_INVALID_VOLUME);
    assert(ports[a&0xff].volume[0]==VOLUME_0DB && ports[a&0xff].volume[2]==0);
    assert(audio_volume(a,0xff,NULL)==ERR_INVALID_POINTER);
    float data[256*8]={0};
    assert(audio_output(a,data)==256*8);
    const OutputParam group[]={{a,data},{b,data}},duplicate[]={{a,data},{a,data}},different[]={{a,data},{c,data}};
    assert(audio_outputs(group,2)==256);
    assert(audio_outputs(duplicate,2)==ERR_INVALID_PORT);
    assert(audio_outputs(different,2)==ERR_INVALID_SIZE);
    assert(audio_close(a)==0 && audio_close(b)==0 && audio_close(c)==0);
    munmap(memory,(size_t)page*2);
    puts("Scalar volume guard-page, channel masks, and grouped return contracts passed");
}
