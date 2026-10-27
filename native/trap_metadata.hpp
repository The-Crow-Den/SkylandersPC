// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <array>
#include <span>
#include <string_view>
#include <algorithm>
#include <openssl/evp.h>

// Read-only format interpretation. The per-tag cipher keys are derived in
// memory; format seed material stays in the user's private asset cache.
namespace TrapMetadata {
inline constexpr std::array<int,47> portrait_by_id{{-1,20,26,33,14,40,45,8,36,3,6,21,35,23,2,19,0,11,32,1,22,28,7,18,13,44,30,39,29,31,25,24,10,37,16,4,15,34,42,41,12,17,43,9,5,27,38}};
inline unsigned crc(std::span<const unsigned char> data) {
    unsigned value=0xffff;
    for(auto byte:data){value^=unsigned(byte)<<8;for(int bit=0;bit<8;++bit)value=((value<<1)^((value&0x8000)?0x1021:0))&0xffff;}
    return value;
}
// -1 = unreadable/unknown, 0 = empty, >0 = stored villain ID.
inline int capture(const std::array<unsigned char,1024>& raw,std::string_view seed) {
    const auto nonzero=[&](unsigned block){return std::any_of(raw.begin()+block,raw.begin()+block+16,[](auto b){return b!=0;});};
    if(!nonzero(0x80)&&!nonzero(0x240))return 0;
    if(seed.empty()||seed.size()>256)return -1;
    auto plain=raw;
    for(unsigned block=8;block<64;++block) {
        if(block%4==3||!nonzero(block*16))continue;
        std::array<unsigned char,16> key{};unsigned length=0;
        auto* hash=EVP_MD_CTX_new();if(!hash)return -1;
        const auto index=static_cast<unsigned char>(block);
        const bool hashed=EVP_DigestInit_ex(hash,EVP_md5(),nullptr)==1 && EVP_DigestUpdate(hash,raw.data(),32)==1 &&
            EVP_DigestUpdate(hash,&index,1)==1 && EVP_DigestUpdate(hash,seed.data(),seed.size())==1 && EVP_DigestFinal_ex(hash,key.data(),&length)==1;
        EVP_MD_CTX_free(hash);if(!hashed||length!=16)return -1;
        auto* cipher=EVP_CIPHER_CTX_new();if(!cipher)return -1;int bytes=0,tail=0;
        const bool ok=EVP_DecryptInit_ex(cipher,EVP_aes_128_ecb(),nullptr,key.data(),nullptr)==1 && EVP_CIPHER_CTX_set_padding(cipher,0)==1 &&
            EVP_DecryptUpdate(cipher,plain.data()+block*16,&bytes,raw.data()+block*16,16)==1 && EVP_DecryptFinal_ex(cipher,plain.data()+block*16+bytes,&tail)==1;
        EVP_CIPHER_CTX_free(cipher);if(!ok||bytes+tail!=16)return -1;
    }
    const auto valid=[&](unsigned area){
        if(!nonzero(area))return false;
        std::array<unsigned char,16> header{};std::copy_n(plain.data()+area,16,header.data());header[14]=5;header[15]=0;
        return crc(header)==(unsigned(plain[area+14])|(unsigned(plain[area+15])<<8));
    };
    const bool first=valid(0x80),second=valid(0x240);if(!first&&!second)return -1;
    const unsigned area=second&&(!first||static_cast<unsigned char>(plain[0x89]+1)==plain[0x249])?0x240:0x80;
    const auto count=plain[area+1];if(count>6)return -1;if(!count)return 0;
    const unsigned id=plain[area+0x10];return id>0&&id<portrait_by_id.size()?static_cast<int>(id):-1;
}
}
