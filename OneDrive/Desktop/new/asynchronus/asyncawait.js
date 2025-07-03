//async await making a brownie

const preHeatOven = () => {
    return new Promise((resolve,reject) => {
        const preheatoven = true
        setTimeout(() => {
            if(preheatoven){
                resolve("pre heat oven to 100 degree c")
            }
            else{
                reject("failed ")
            }
        }, 1000);
    })
}

const addSugarandChocoChips = () => {
    return new Promise((resolve,reject) => {
        const addChoco = true  
        setTimeout(() => {
            if(addChoco){
                resolve("add choco chips")
            }
            else{
                reject("failed")
            }
        }, 1000);
    })
}

const addFlour = () => {
    return new Promise((resolve,reject) => {
        const addFlour = true
        setTimeout(() => {
            if(addFlour){
                resolve("bake")
            }
            else{
                reject("failed")
            }
        }, 1000);
    })
}

const makeChocoBrownie = async () => {
    try{
        const task1 =  await preHeatOven()
        console.log(task1)
    
        const task2 = await addSugarandChocoChips()
        console.log(task2)

        const task3 = await addFlour()
        console.log(task3)

        console.log("browniw ready")
    }
    catch(err){
        console.log(err)
    }
}

makeChocoBrownie()