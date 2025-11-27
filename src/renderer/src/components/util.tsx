
// produces a 'hash' from a string and maps it to luminsity from 20-100
// low lum is just black
const map_lum = (string) => {
    let hash = 0;
    for (const char of string) {
        hash = (hash << 5) - hash + char.charCodeAt(0);
        hash |= 0; // Constrain to 32bit integer
    }
    return Math.abs(Math.trunc(hash % 80)) + 20
}

export { map_lum };
