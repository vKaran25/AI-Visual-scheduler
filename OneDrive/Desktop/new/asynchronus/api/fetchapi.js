// //fetch API 
// fetch('https://dummyjson.com/products/add',{
//     method: 'POST',
//     headers:{
//         'Content-type':'application/json'
//     },
//     body:JSON.stringify({
//         description:'assphone 23',
//         price:'23.98'
//     })
// })
// .then(response => response.json())
// .then(data => console.log(data))
// .catch(err => console.log(err))

const getAllProducts = async () => {
    try{
        const response = await fetch('https://dummyjson.com/products/')
        const json = await response.json()
        console.log(json)
    }
    catch(err){
        console.log(err)
    }
} 

getAllProducts()