// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <map>
#include <istream>
#include <string>
namespace PortalPortraits {
class Index {
    std::map<std::pair<unsigned,unsigned>,int> entries;
public:
    bool load(std::istream& input) {
        entries.clear();std::string magic;unsigned columns=0,rows=0;
        if(!(input>>magic>>columns>>rows)||magic!="SKYPORTRAITS1"||!columns||columns>32||!rows||rows>64)return false;
        unsigned id=0,variant=0,cell=0;unsigned count=0;
        while(input>>id) {
            if(!(input>>variant>>cell)||id>65535||variant>65535||cell>=columns*rows||++count>2048||
               !entries.emplace(std::pair{id,variant},static_cast<int>(cell)).second){entries.clear();return false;}
        }
        if(!input.eof()){entries.clear();return false;}
        return true;
    }
    int find(unsigned id,unsigned variant) const {
        if(auto exact=entries.find({id,variant});exact!=entries.end())return exact->second;
        if(auto base=entries.find({id,0});base!=entries.end())return base->second;
        auto first=entries.lower_bound({id,0});
        return first!=entries.end()&&first->first.first==id?first->second:-1;
    }
};
}
