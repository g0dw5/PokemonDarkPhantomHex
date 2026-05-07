# Pokemon Hack ROM Character Map Notes

- Target ROM: `/Users/wang.song/Desktop/pokemon/漆黑的魅影 5.0EX BW.gba`.
- ROM header: `POKEMON EMER`, game code `BPEE`, so it is Emerald-based.
- The ROM uses the Pokemon GBA Chinese font patch encoding from `Wokann/Pokemon_GBA_Font_Patch`.
- Primary charmap source: `Pokemon_GBA_Font_Patch/pokeE/PMRSEFRLG_charmap.txt`.
- The official charmap is now embedded directly in `editor/rom_data.py`; the editor no longer reads or writes `data/rom_text.json`.
- Chinese characters are two-byte tokens in GB2312 order, from `0100=啊` through `1E5D=齄`.
- Chinese punctuation is single-byte: `36=;`, `37=。`, `38=－`, `39=~`, `3A=、`, `3B=，`, `3C=！`, `3D=？`, `3E=：`.
- Important tokenizer rule: use longest-match tokens and preserve low-byte `00` Chinese codes such as `0400=肤`, `0800=块`, `0A00=牛`, `0F00=野`, `1000=噪`. Do not treat `00` as padding before trying a two-byte match.
- ROM special case: token `71` appears in move 128 name before `07D5 05BB`; it renders as a narrow blank and should be mapped as `U+2009`.
- Snapshot config with only observed mappings: `data/rom_used_charmap.json`.
