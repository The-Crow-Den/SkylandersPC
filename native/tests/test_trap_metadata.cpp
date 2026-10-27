// SPDX-License-Identifier: GPL-3.0-or-later
#include "../trap_metadata.hpp"
#include "../portal_portraits.hpp"
#include <sstream>
#include <stdexcept>
#include <iostream>
using Bytes=std::array<unsigned char,1024>;
static constexpr std::string_view seed="synthetic-format-fixture";
void require(bool ok){if(!ok)throw std::runtime_error("trap metadata contract failed");}
void seal(Bytes& bytes,unsigned area,unsigned count,unsigned id,unsigned counter){
    bytes[area+1]=static_cast<unsigned char>(count);bytes[area+9]=static_cast<unsigned char>(counter);bytes[area+0x10]=static_cast<unsigned char>(id);
    bytes[area+14]=5;bytes[area+15]=0;const auto value=TrapMetadata::crc({bytes.data()+area,16});bytes[area+14]=static_cast<unsigned char>(value);bytes[area+15]=static_cast<unsigned char>(value>>8);
}
Bytes encrypt(Bytes bytes){const auto plain=bytes;
    for(unsigned block=8;block<64;++block){if(block%4==3||std::all_of(plain.begin()+block*16,plain.begin()+block*16+16,[](auto b){return !b;}))continue;
        std::array<unsigned char,16> key{};unsigned length=0;auto* md=EVP_MD_CTX_new();const auto index=static_cast<unsigned char>(block);
        require(EVP_DigestInit_ex(md,EVP_md5(),nullptr)==1&&EVP_DigestUpdate(md,plain.data(),32)==1&&EVP_DigestUpdate(md,&index,1)==1&&EVP_DigestUpdate(md,seed.data(),seed.size())==1&&EVP_DigestFinal_ex(md,key.data(),&length)==1);EVP_MD_CTX_free(md);
        auto* context=EVP_CIPHER_CTX_new();int written=0,tail=0;require(EVP_EncryptInit_ex(context,EVP_aes_128_ecb(),nullptr,key.data(),nullptr)==1&&EVP_CIPHER_CTX_set_padding(context,0)==1&&EVP_EncryptUpdate(context,bytes.data()+block*16,&written,plain.data()+block*16,16)==1&&EVP_EncryptFinal_ex(context,bytes.data()+block*16+written,&tail)==1);EVP_CIPHER_CTX_free(context);
    }return bytes;
}
int main(){try{
    Bytes bytes{};require(TrapMetadata::capture(bytes,"")==0);bytes[0]=17;seal(bytes,0x80,1,19,254);
    require(TrapMetadata::capture(encrypt(bytes),seed)==19);require(TrapMetadata::capture(encrypt(bytes),"wrong")<0);
    seal(bytes,0x240,1,22,255);require(TrapMetadata::capture(encrypt(bytes),seed)==22);
    seal(bytes,0x80,1,20,0);require(TrapMetadata::capture(encrypt(bytes),seed)==20);
    seal(bytes,0x80,7,20,0);require(TrapMetadata::capture(encrypt(bytes),seed)<0);
    seal(bytes,0x80,0,0,0);require(TrapMetadata::capture(encrypt(bytes),seed)==0);
    require(TrapMetadata::portrait_by_id[19]==1&&TrapMetadata::portrait_by_id[20]==22);
    PortalPortraits::Index index;std::istringstream good("SKYPORTRAITS1 16 20\n14 0 46\n462 0 51\n");require(index.load(good));require(index.find(14,0)==46&&index.find(462,12288)==51&&index.find(6,0)==-1);
    std::istringstream bad("SKYPORTRAITS1 16 20\n14 0 320\n");require(!index.load(bad)&&index.find(14,0)==-1);
    std::cout<<"Trap metadata, counter wrap, invalid data and portrait identity checks passed\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
