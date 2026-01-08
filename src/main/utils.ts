const sum = (arr: number[]): number => {
    return arr.reduce((acc, e) => acc += e, 0)
}

export {
    sum
};