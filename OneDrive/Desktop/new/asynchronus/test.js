//synchronus programming
// console.log(" 1. hello")
// console.log("2 .my name is karan")
// console.log("3. pero programmer")

function task1(callback){
    setTimeout(() => {
        console.log("1. bye")
        callback()
    }, 2000);
}
function task2(callback){
    setTimeout(() => {
        console.log("2. my name is karan")
        callback();
    }, 1000);    
}
function task3(callback){
    setTimeout(() => {
        console.log("3 .hello")
        callback()
    }, 500);
}

task1(() => {
    task2(() => {
        task3(() => {
                                   //nested callbacks callback hell
        })
    })
})