const showMsg = (callback) => {
    console.log(callback)
}

const firstMsg = (callback) => {
    setTimeout(() => {
        showMsg("hello")
        callback()
    }, 2000);
}

const secondMsg = () => {
    showMsg("world")
}

firstMsg(secondMsg)   // another example of callback hell