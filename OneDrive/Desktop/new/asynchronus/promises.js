// const promise = new Promise((resolve,reject) => {
//     const allWentWell = true
//     if(allWentWell){
//         resolve('all ok')
//     }
//     else{
//         reject('something wrong')
//     }
// })
// console.log(promise)

// const promise = new Promise((resolve,reject) => {
//     N = 10
//     const randint = Math.floor(Math.random() * N)
//     setTimeout(() => {
//        if(randint<4){
//         console.log('less than 4')
//        } 
//        else{
//         console.log('greater than 4')
//        }
//     },2000);
// })
// console.log(promise)

// const promiseOne = new Promise((resolve,reject) => {
//     resolve('resolved')
// })
// const promisetwo = new Promise((resolve,reject) => {
//     resolve('resolved')
// })
// const promisethree = new Promise((resolve,reject) => {
//     reject('reject')
// })

// promiseOne.then((value) => {          //.then catch are used to consume the promise 
//     console.log(value);
//     return promisetwo
// }).then((value) => {
//     console.log(value)
//     return promisethree
// }).catch((error) => {
//     console.log(error)
// })


const promise1 = new Promise((resolve,reject) => {
    setTimeout(() => {
        resolve("hello")
    }, 2000);
})
const promise2 = new Promise((resolve,reject) => {
    setTimeout(() => {
        reject("world")
    },2500)
})
Promise.all([promise1,promise2])
.then((data) => {
    console.log(data[0],data[1])                 //consume multiple promise at same time it is used when fetching data from multiple api or making database calls
})
.catch((err) => {
    console.log(err)
})