const loadFact = async () => {
    try{
        const fetchFact = await fetch('https://v2.jokeapi.dev/joke/Any?blacklistFlags=nsfw,religious,political,racist,sexist,explicit&type=single',{
            headers:{
                Accept:'application/json'
            }
        });

        const factdata = await fetchFact.json()
        document.getElementById('jokecontainer').innerHTML = factdata.joke
    }
    catch(error){
        console.log(error)
    }
}
document.getElementById('jokebtn').addEventListener("click",loadFact)



//https://v2.jokeapi.dev/joke/Any?blacklistFlags=nsfw,religious,political,racist,sexist,explicit
